"""End-to-end walk of the flow the app actually performs.

Register → six questionnaire steps → plan calculation → meal plan → shopping list →
diary → photo recognition. If this passes, the product's spine works.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from sqlalchemy import text

from tests.conftest import last_sms_code, new_phone, pay, sign_in

ONBOARDING_STEPS = [
    ("personal", {"sex": "male", "birth_date": "1997-04-12", "height_cm": 182, "weight_kg": 84}),
    ("goal", {"goal": "lose", "rate_pct": 0.18, "target_weight_kg": 78}),
    ("restrictions", {"diet": "omnivore", "allergens": [], "excluded_product_ids": []}),
    ("budget", {"budget_type": "fixed_day", "amount": 600, "currency": "RUB"}),
    ("activity", {"activity_level": "high"}),
    ("workout-location", {"location": "home"}),
]


async def complete_onboarding(client: AsyncClient) -> dict:
    for step, payload in ONBOARDING_STEPS:
        response = await client.patch(f"/v1/onboarding/{step}", json=payload)
        assert response.status_code == 200, response.text
    response = await client.post("/v1/onboarding/complete")
    assert response.status_code == 200, response.text
    return response.json()


async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"


@pytest.mark.parametrize(
    "page",
    ["privacy", "terms", "consent", "health-consent", "ai-consent", "recommendations"],
)
async def test_legal_pages_are_public_html(client: AsyncClient, page: str):
    response = await client.get(f"/legal/{page}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>" in response.text and "{operator}" not in response.text
    assert (await client.get("/legal/unknown")).status_code == 404


async def test_phone_sign_in_creates_then_reuses_the_account(client: AsyncClient):
    phone = new_phone()
    first = await sign_in(client, f"+7 ({phone[1:4]}) {phone[4:7]}-{phone[7:9]}-{phone[9:]}")
    again = await sign_in(client, "8" + phone[1:])
    me = await client.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {again['access_token']}"}
    )
    assert me.json()["phone"] == phone
    first_me = await client.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {first['access_token']}"}
    )
    assert first_me.json()["id"] == me.json()["id"]


async def test_wrong_code_is_rejected_and_attempts_are_limited(client: AsyncClient):
    phone = new_phone()
    await client.post("/v1/auth/phone/code", json={"phone": phone})
    right = last_sms_code(phone)
    wrong = "000000" if right != "000000" else "111111"
    for _ in range(5):
        response = await client.post(
            "/v1/auth/phone/verify",
            json={"phone": phone, "code": wrong, "personal_data_consent": True},
        )
        assert response.status_code == 401
    # After five failures even the right code no longer works.
    locked = await client.post(
        "/v1/auth/phone/verify",
        json={"phone": phone, "code": right, "personal_data_consent": True},
    )
    assert locked.status_code == 401
    assert locked.json()["detail"] == "code expired"


async def test_codes_cannot_be_requested_back_to_back(client: AsyncClient, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "phone_code_resend_seconds", 60)
    phone = new_phone()
    assert (await client.post("/v1/auth/phone/code", json={"phone": phone})).status_code == 200
    again = await client.post("/v1/auth/phone/code", json={"phone": phone})
    assert again.status_code == 429
    assert int(again.headers["Retry-After"]) > 0


async def test_only_russian_mobile_numbers_are_accepted(client: AsyncClient):
    for phone in ("+1 650 555 0100", "+7 495 123-45-67", "12345"):
        response = await client.post("/v1/auth/phone/code", json={"phone": phone})
        assert response.status_code == 422, phone


async def test_a_code_works_once(client: AsyncClient):
    phone = new_phone()
    await sign_in(client, phone)
    reused = await client.post(
        "/v1/auth/phone/verify", json={"phone": phone, "code": last_sms_code(phone)}
    )
    assert reused.status_code == 401


async def test_refresh_token_round_trip(client: AsyncClient):
    tokens = await sign_in(client)
    refreshed = await client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != ""


async def test_access_token_is_not_accepted_as_refresh_token(client: AsyncClient):
    tokens = await sign_in(client)
    response = await client.post(
        "/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )
    assert response.status_code == 401


async def test_protected_endpoint_requires_a_token(client: AsyncClient):
    assert (await client.get("/v1/me/targets")).status_code == 401


async def test_oauth_stub_creates_and_then_matches_an_identity(client: AsyncClient):
    body = {"id_token": "test:abc123", "email": "vk-user@example.com", "personal_data_consent": True}
    first = await client.post("/v1/auth/oauth/vk", json=body)
    assert first.status_code == 200
    second = await client.post("/v1/auth/oauth/vk", json=body)
    assert second.status_code == 200


async def test_unsupported_oauth_provider_is_rejected(client: AsyncClient):
    response = await client.post(
        "/v1/auth/oauth/facebook", json={"id_token": "test:x"}
    )
    assert response.status_code == 400


# ------------------------------------------------------------------------ onboarding


async def test_onboarding_tracks_progress_step_by_step(auth_client: AsyncClient):
    session = (await auth_client.get("/v1/onboarding/session")).json()
    assert session["current_step"] == 1
    assert session["completed_steps"] == []

    for index, (step, payload) in enumerate(ONBOARDING_STEPS, start=1):
        body = (await auth_client.patch(f"/v1/onboarding/{step}", json=payload)).json()
        assert body["completed_steps"] == list(range(1, index + 1))

    # The draft survives a "reopen the app" round trip.
    resumed = (await auth_client.get("/v1/onboarding/session")).json()
    assert resumed["completed_steps"] == [1, 2, 3, 4, 5, 6]


async def test_complete_before_all_steps_is_rejected(auth_client: AsyncClient):
    await auth_client.patch("/v1/onboarding/personal", json=ONBOARDING_STEPS[0][1])
    response = await auth_client.post("/v1/onboarding/complete")
    assert response.status_code == 400
    assert "not completed" in response.json()["detail"]


async def test_budget_step_requires_an_amount_unless_unlimited(auth_client: AsyncClient):
    bad = await auth_client.patch(
        "/v1/onboarding/budget", json={"budget_type": "fixed_week"}
    )
    assert bad.status_code == 422

    ok = await auth_client.patch(
        "/v1/onboarding/budget", json={"budget_type": "unlimited"}
    )
    assert ok.status_code == 200


async def test_implausible_body_metrics_are_rejected(auth_client: AsyncClient):
    response = await auth_client.patch(
        "/v1/onboarding/personal",
        json={"sex": "male", "birth_date": "2020-01-01", "height_cm": 182, "weight_kg": 84},
    )
    assert response.status_code == 422


async def test_completing_onboarding_returns_targets_and_a_plan(auth_client: AsyncClient):
    result = await complete_onboarding(auth_client)

    targets = result["targets"]
    assert result["activity_coefficient"] == 1.9
    # 84 kg / 182 cm / 28 y male, high activity, fixed 15% deficit.
    assert 1800 < targets["bmr_kcal"] < 1950
    assert targets["tdee_kcal"] == pytest.approx(targets["bmr_kcal"] * 1.9, rel=0.01)
    assert targets["target_kcal"] == pytest.approx(targets["tdee_kcal"] * 0.85, rel=0.01)
    assert targets["protein_g"] == pytest.approx(targets["target_kcal"] * 0.30 / 4, abs=1)
    assert result["plan_id"]


async def test_onboarding_location_routes_workout_equipment(auth_client: AsyncClient):
    await complete_onboarding(auth_client)

    preferences = (await auth_client.get("/v1/workouts/preferences")).json()
    assert preferences["location"] == "home"
    assert set(preferences["equipment"]) == {"вес тела", "без оборудования"}

    response = await auth_client.patch(
        "/v1/onboarding/workout-location", json={"location": "gym"}
    )
    assert response.status_code == 200

    # Re-computing after changing the route applies the gym branch: an empty
    # equipment list means the generator can use the full gym catalogue.
    response = await auth_client.post("/v1/onboarding/complete")
    assert response.status_code == 200, response.text
    preferences = (await auth_client.get("/v1/workouts/preferences")).json()
    assert preferences["location"] == "gym"
    assert preferences["equipment"] == []


async def test_targets_are_readable_after_onboarding(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    response = await auth_client.get("/v1/me/targets")
    assert response.status_code == 200
    assert response.json()["target_kcal"] > 0


# ------------------------------------------------------------------------ meal plans


async def test_generated_plan_covers_the_week_and_respects_the_budget(
    auth_client: AsyncClient,
):
    plan_id = (await complete_onboarding(auth_client))["plan_id"]
    plan = (await auth_client.get(f"/v1/meal-plans/{plan_id}")).json()

    assert len(plan["days"]) == 7
    assert plan["budget_total"] == 600 * 7
    assert plan["cost_total"] <= plan["budget_total"]

    for day in plan["days"]:
        assert len(day["items"]) == 4
        assert {item["meal_type"] for item in day["items"]} == {
            "breakfast",
            "lunch",
            "dinner",
            "snack",
        }
        # No dish twice in one day.
        slugs = [item["recipe_slug"] for item in day["items"]]
        assert len(slugs) == len(set(slugs))
        # Energy lands close to target — this is the product's core promise.
        assert day["kcal"] == pytest.approx(plan["target_kcal"], rel=0.10)


async def test_recipe_images_are_generated_once_for_today(
    auth_client: AsyncClient, tmp_path, monkeypatch
):
    await complete_onboarding(auth_client)

    from app.core.config import settings
    from app.jobs.recipe_images import GeneratedImage, run_recipe_image_job

    class FakeImageProvider:
        def __init__(self):
            self.calls = []

        async def generate(self, recipe):
            self.calls.append(recipe.slug)
            return GeneratedImage(b"fake-png")

    provider = FakeImageProvider()
    monkeypatch.setattr(settings, "recipe_image_storage_dir", str(tmp_path / "recipes"))
    monkeypatch.setattr(settings, "recipe_image_public_base_url", "http://test")

    first = await run_recipe_image_job(provider=provider, run_date=date.today())
    second = await run_recipe_image_job(provider=provider, run_date=date.today())

    assert first == len(provider.calls) > 0
    assert second == 0
    assert len(provider.calls) == len(set(provider.calls))
    assert all((tmp_path / "recipes" / f"{slug}.png").exists() for slug in provider.calls)


async def test_plan_is_scoped_to_its_owner(auth_client: AsyncClient, client: AsyncClient):
    plan_id = (await complete_onboarding(auth_client))["plan_id"]

    other = AsyncClient(transport=auth_client._transport, base_url="http://test")
    registration = await sign_in(other)
    other.headers["Authorization"] = f"Bearer {registration['access_token']}"
    response = await other.get(f"/v1/meal-plans/{plan_id}")
    await other.aclose()
    assert response.status_code == 404


async def test_shopping_list_aggregates_ingredients_with_costs(auth_client: AsyncClient):
    plan_id = (await complete_onboarding(auth_client))["plan_id"]
    response = await auth_client.get(f"/v1/meal-plans/{plan_id}/shopping-list")
    assert response.status_code == 200

    body = response.json()
    assert body["entries"]
    slugs = [entry["slug"] for entry in body["entries"]]
    assert len(slugs) == len(set(slugs)), "each product must appear once"
    assert all(entry["grams"] > 0 for entry in body["entries"])
    assert body["total_estimated_cost"] > 0


async def test_swapping_a_meal_keeps_the_rest_of_the_day(auth_client: AsyncClient):
    plan_id = (await complete_onboarding(auth_client))["plan_id"]
    plan = (await auth_client.get(f"/v1/meal-plans/{plan_id}")).json()

    day = plan["days"][0]
    victim = next(item for item in day["items"] if item["meal_type"] == "lunch")
    untouched = {
        item["meal_type"]: item["recipe_slug"]
        for item in day["items"]
        if item["meal_type"] != "lunch"
    }

    response = await auth_client.post(
        f"/v1/meal-plans/{plan_id}/items/{victim['id']}/swap"
    )
    assert response.status_code == 200, response.text

    new_day = response.json()["days"][0]
    new_lunch = next(item for item in new_day["items"] if item["meal_type"] == "lunch")
    assert new_lunch["recipe_slug"] != victim["recipe_slug"]
    for meal_type, slug in untouched.items():
        kept = next(item for item in new_day["items"] if item["meal_type"] == meal_type)
        assert kept["recipe_slug"] == slug


async def test_generating_a_plan_needs_a_completed_profile(auth_client: AsyncClient):
    response = await auth_client.post("/v1/meal-plans/generate", json={"days": 3})
    assert response.status_code == 409


async def test_recipe_details_include_instructions_approximate_prices_and_favorites(
    auth_client: AsyncClient,
):
    await complete_onboarding(auth_client)
    recipes = (await auth_client.get("/v1/catalog/recipes", params={"limit": 1})).json()
    slug = recipes[0]["slug"]
    detail = (await auth_client.get(f"/v1/catalog/recipes/{slug}")).json()
    assert detail["instructions"]
    assert detail["ingredients"]
    assert "примерные" in detail["price_notice"].lower()
    assert (await auth_client.post(f"/v1/catalog/recipes/{slug}/favorite")).json()["is_favorite"]
    assert (await auth_client.delete(f"/v1/catalog/recipes/{slug}/favorite")).json()["is_favorite"] is False


async def test_workout_calendar_execution_and_completion(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    monday = date.today() + timedelta(days=(7 - date.today().weekday()) % 7)
    response = await auth_client.get(
        "/v1/workouts/calendar",
        params={"date_from": monday.isoformat(), "date_to": (monday + timedelta(days=6)).isoformat()},
    )
    assert response.status_code == 200, response.text
    workouts = response.json()
    assert workouts
    workout = (await auth_client.get(f"/v1/workouts/{workouts[0]['id']}")).json()
    assert workout["exercises"]
    exercise_id = workout["exercises"][0]["id"]
    updated = await auth_client.patch(
        f"/v1/workouts/{workout['id']}/exercises/{exercise_id}",
        json={"is_completed": True, "is_skipped": False},
    )
    assert updated.json()["completed_count"] == 1
    completed = await auth_client.post(f"/v1/workouts/{workout['id']}/complete")
    assert completed.json()["status"] == "completed"


async def test_exercise_registry_is_searchable_and_linked_to_new_workouts(auth_client: AsyncClient):
    meta = await auth_client.get("/v1/exercises/meta")
    assert meta.status_code == 200
    assert meta.json()["total"] >= 180
    assert "грудь" in meta.json()["muscle_groups"]
    assert "икры" in meta.json()["muscle_groups"]

    chest = await auth_client.get("/v1/exercises", params={"muscle": "грудь"})
    assert chest.status_code == 200
    assert any(item["id"] == "push-up" for item in chest.json())

    await complete_onboarding(auth_client)
    monday = date.today() + timedelta(days=(7 - date.today().weekday()) % 7)
    calendar = await auth_client.get(
        "/v1/workouts/calendar",
        params={"date_from": monday.isoformat(), "date_to": (monday + timedelta(days=13)).isoformat()},
    )
    assert calendar.status_code == 200
    workouts = [
        (await auth_client.get(f"/v1/workouts/{item['id']}")).json()
        for item in calendar.json()
    ]
    catalog_ids = {
        exercise["catalog_id"] for workout in workouts for exercise in workout["exercises"]
    }
    assert len(catalog_ids) >= 16
    assert all(exercise["primary_muscle"] for workout in workouts for exercise in workout["exercises"])
    assert all("secondary_muscles" in exercise for workout in workouts for exercise in workout["exercises"])
    assert all(workout["body_sex"] == "male" for workout in workouts)
    assert any(exercise["equipment"] for workout in workouts for exercise in workout["exercises"])


async def test_home_route_has_full_bodyweight_workouts(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    monday = date.today() + timedelta(days=(7 - date.today().weekday()) % 7)
    calendar = await auth_client.get(
        "/v1/workouts/calendar",
        params={"date_from": monday.isoformat(), "date_to": (monday + timedelta(days=13)).isoformat()},
    )
    assert calendar.status_code == 200, calendar.text
    assert calendar.json()

    workouts = [
        (await auth_client.get(f"/v1/workouts/{item['id']}")).json()
        for item in calendar.json()
    ]
    allowed = {"вес тела", "без оборудования"}
    assert all(len(workout["exercises"]) >= 4 for workout in workouts)
    assert all(
        exercise["equipment"] in allowed
        for workout in workouts
        for exercise in workout["exercises"]
    )


async def test_workout_preferences_limit_equipment_and_rebuild_planned_workouts(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    saved = await auth_client.patch(
        "/v1/workouts/preferences",
        json={
            "equipment": ["резинка"],
            "focus_muscles": ["грудь", "ягодицы"],
            "rebuild_planned": True,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["focus_muscles"] == ["грудь", "ягодицы"]

    monday = date.today() + timedelta(days=(7 - date.today().weekday()) % 7)
    workout = (await auth_client.get("/v1/workouts/today", params={"day": monday.isoformat()})).json()
    assert {item["equipment"] for item in workout["exercises"]} <= {"вес тела", "без оборудования", "резинка"}
    assert any(item["primary_muscle"] == "грудь" for item in workout["exercises"])


async def test_progress_entry_overview_and_report(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    created = await auth_client.post(
        "/v1/progress/entries",
        json={"day": date.today().isoformat(), "weight_kg": 82.5, "waist_cm": 88, "note": "Старт"},
    )
    assert created.status_code == 201, created.text
    overview = (await auth_client.get("/v1/progress/overview")).json()
    assert overview["current_weight_kg"] == 82.5
    assert overview["entries"][0]["note"] == "Старт"
    report = (await auth_client.get("/v1/progress/report")).json()
    assert report["summary"]["current_weight_kg"] == 82.5


# ---------------------------------------------------------------------------- diary


async def test_diary_logging_and_daily_summary(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    products = (await auth_client.get("/v1/catalog/products", params={"q": "греч"})).json()
    assert products, "seeded catalogue should contain buckwheat"

    today = date.today().isoformat()
    created = await auth_client.post(
        "/v1/diary/entries",
        json={
            "day": today,
            "meal_type": "lunch",
            "product_id": products[0]["id"],
            "grams": 150,
        },
    )
    assert created.status_code == 201, created.text
    entry = created.json()
    expected_kcal = round(products[0]["kcal_per_100g"] * 1.5, 1)
    assert entry["kcal"] == pytest.approx(expected_kcal, abs=0.2)

    summary = (await auth_client.get(f"/v1/diary/{today}")).json()
    assert summary["kcal"] == pytest.approx(expected_kcal, abs=0.2)
    assert summary["target_kcal"] > 0


async def test_diary_entry_requires_exactly_one_reference(auth_client: AsyncClient):
    response = await auth_client.post(
        "/v1/diary/entries",
        json={"day": date.today().isoformat(), "meal_type": "lunch", "grams": 100},
    )
    assert response.status_code == 422


async def test_diary_accepts_manual_calorie_entry(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    today = date.today().isoformat()
    response = await auth_client.post(
        "/v1/diary/entries",
        json={
            "day": today,
            "meal_type": "dinner",
            "name": "Домашний ужин",
            "kcal": 640,
            "protein_g": 32,
            "fat_g": 24,
            "carbs_g": 68,
        },
    )

    assert response.status_code == 201, response.text
    entry = response.json()
    assert entry["name"] == "Домашний ужин"
    assert entry["kcal"] == 640
    assert entry["grams"] == 1


async def test_repeat_meal_copies_yesterdays_entries(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    products = (await auth_client.get("/v1/catalog/products", params={"q": "рис"})).json()
    yesterday = date.today() - timedelta(days=1)

    await auth_client.post(
        "/v1/diary/entries",
        json={
            "day": yesterday.isoformat(),
            "meal_type": "breakfast",
            "product_id": products[0]["id"],
            "grams": 200,
        },
    )
    response = await auth_client.post(
        "/v1/diary/repeat",
        json={
            "source_day": yesterday.isoformat(),
            "target_day": date.today().isoformat(),
            "meal_type": "breakfast",
        },
    )
    assert response.status_code == 200
    copies = response.json()
    assert len(copies) == 1
    assert copies[0]["source"] == "repeat"
    assert copies[0]["grams"] == 200


async def test_deleting_a_diary_entry(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    products = (await auth_client.get("/v1/catalog/products", params={"limit": 1})).json()
    entry = (
        await auth_client.post(
            "/v1/diary/entries",
            json={
                "day": date.today().isoformat(),
                "meal_type": "snack",
                "product_id": products[0]["id"],
                "grams": 50,
            },
        )
    ).json()

    assert (await auth_client.delete(f"/v1/diary/entries/{entry['id']}")).status_code == 204
    summary = (await auth_client.get(f"/v1/diary/{date.today().isoformat()}")).json()
    assert summary["entries"] == []


# --------------------------------------------------------------------------- vision


def fake_photo(seed: bytes = b"lunch") -> dict:
    return {"image": ("meal.jpg", io.BytesIO(seed * 200), "image/jpeg")}


async def test_vision_recognition_returns_editable_candidates(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    response = await auth_client.post("/v1/vision/recognize", files=fake_photo())
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["requires_confirmation"] is True, "auto-logging a guess is never acceptable"
    assert body["candidates"]
    for candidate in body["candidates"]:
        assert candidate["product_id"]
        assert candidate["grams_estimate"] > 0
        assert 0.0 <= candidate["confidence"] <= 1.0
        # Nutrition is derived from our catalogue, not from the model.
        assert candidate["kcal"] >= 0


async def test_vision_rejects_non_images(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    response = await auth_client.post(
        "/v1/vision/recognize",
        files={"image": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert response.status_code == 415


async def test_identical_photo_is_not_charged_twice(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    first = await auth_client.post("/v1/vision/recognize", files=fake_photo(b"same"))
    second = await auth_client.post("/v1/vision/recognize", files=fake_photo(b"same"))
    assert first.json()["recognition_id"] == second.json()["recognition_id"]


async def test_trial_photo_quota_is_enforced(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    for index in range(5):
        response = await auth_client.post(
            "/v1/vision/recognize", files=fake_photo(f"photo-{index}".encode())
        )
        assert response.status_code == 200
    blocked = await auth_client.post("/v1/vision/recognize", files=fake_photo(b"sixth"))
    assert blocked.status_code == 402
    assert "limit" in blocked.json()["detail"]


async def test_confirming_a_recognition_writes_the_diary_and_records_the_edit(
    auth_client: AsyncClient,
):
    await complete_onboarding(auth_client)
    recognition = (
        await auth_client.post("/v1/vision/recognize", files=fake_photo(b"confirm"))
    ).json()
    candidate = recognition["candidates"][0]

    response = await auth_client.post(
        f"/v1/vision/{recognition['recognition_id']}/confirm",
        json={
            "day": date.today().isoformat(),
            "meal_type": "dinner",
            # The user corrects the estimate — the delta is the accuracy dataset.
            "items": [{"product_id": candidate["product_id"], "grams": candidate["grams_estimate"] + 40}],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["was_edited"] is True

    summary = (await auth_client.get(f"/v1/diary/{date.today().isoformat()}")).json()
    assert any(entry["source"] == "vision" for entry in summary["entries"])


# ------------------------------------------------------------------------ integrations


async def test_trial_cannot_use_assistant(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    response = await auth_client.post(
        "/v1/assistant/chat", json={"message": "Что съесть после тренировки?"}
    )
    assert response.status_code == 402


async def test_pro_tier_assistant_and_retail_offers(auth_client: AsyncClient):
    result = await complete_onboarding(auth_client)
    await pay(auth_client, "pro")
    await auth_client.post("/v1/me/consents", json={"document": "ai_assistant"})
    chat = await auth_client.post(
        "/v1/assistant/chat", json={"message": "Как распределить белок?"}
    )
    assert chat.status_code == 200, chat.text
    conversation_id = chat.json()["conversation_id"]
    history = await auth_client.get(f"/v1/assistant/conversations/{conversation_id}")
    assert history.status_code == 200
    assert [m["role"] for m in history.json()["messages"]] == ["user", "assistant"]

    offers = await auth_client.get(
        f"/v1/meal-plans/{result['plan_id']}/shopping-list/offers"
    )
    assert offers.status_code == 200, offers.text
    offer = offers.json()["offers"][0]
    assert offer["name"]
    assert offer["price_type"] == "estimate"
    assert offer["retailer"] == "Пятёрочка"
    assert offer["available"] is None


async def test_account_deletion_removes_user_and_invalidates_tokens(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    assert (await auth_client.get("/v1/auth/me")).status_code == 200

    deleted = await auth_client.delete("/v1/auth/me")
    assert deleted.status_code == 204
    assert (await auth_client.get("/v1/auth/me")).status_code == 401


async def test_malformed_token_subject_is_401_not_500(client: AsyncClient):
    from app.core.security import create_access_token, create_refresh_token

    client.headers["Authorization"] = f"Bearer {create_access_token('not-a-uuid', 'not-a-uuid')}"
    assert (await client.get("/v1/auth/me")).status_code == 401
    refreshed = await client.post(
        "/v1/auth/refresh", json={"refresh_token": create_refresh_token("not-a-uuid", "not-a-uuid", "x")}
    )
    assert refreshed.status_code == 401


async def test_oauth_ignores_client_supplied_email(client: AsyncClient):
    from app.db.session import SessionLocal

    victim = f"victim-{date.today().isoformat()}-{id(client)}@example.com"
    victim_token = (await sign_in(client))["access_token"]
    headers = {"Authorization": f"Bearer {victim_token}"}
    victim_id = (await client.get("/v1/auth/me", headers=headers)).json()["id"]
    async with SessionLocal() as session:
        await session.execute(
            text("UPDATE users SET email = :email WHERE id = :id"),
            {"email": victim, "id": victim_id},
        )
        await session.commit()

    attacker = await client.post(
        "/v1/auth/oauth/vk",
        json={"id_token": "test:attacker", "email": victim, "personal_data_consent": True},
    )
    assert attacker.status_code == 200
    attacker_me = await client.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {attacker.json()['access_token']}"}
    )
    assert attacker_me.json()["id"] != victim_id
    assert attacker_me.json()["email"] is None


async def test_auth_endpoints_are_rate_limited(client: AsyncClient, monkeypatch):
    from app.core import rate_limit
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 3)
    rate_limit.reset()
    phone = new_phone()
    statuses = [
        (await client.post(
            "/v1/auth/phone/verify", json={"phone": phone, "code": "123456"}
        )).status_code
        for _ in range(4)
    ]
    rate_limit.reset()
    assert statuses == [401, 401, 401, 429]


async def test_peanut_and_seafood_allergies_exclude_catalogue_dishes(auth_client: AsyncClient):
    for step, payload in ONBOARDING_STEPS:
        if step == "restrictions":
            payload = {**payload, "allergens": ["peanut", "seafood"]}
        response = await auth_client.patch(f"/v1/onboarding/{step}", json=payload)
        assert response.status_code == 200, response.text
    result = (await auth_client.post("/v1/onboarding/complete")).json()
    plan = (await auth_client.get(f"/v1/meal-plans/{result['plan_id']}")).json()
    slugs = {item["recipe_slug"] for day in plan["days"] for item in day["items"]}
    assert "oats_banana_pb" not in slugs
    assert not {s for s in slugs if s.startswith("shrimp_")}


async def test_unknown_allergen_is_rejected(auth_client: AsyncClient):
    response = await auth_client.patch(
        "/v1/onboarding/restrictions", json={"diet": "omnivore", "allergens": ["пыльца"]}
    )
    assert response.status_code == 422


async def test_new_weigh_in_recalculates_targets(auth_client: AsyncClient):
    await complete_onboarding(auth_client)
    before = (await auth_client.get("/v1/me/targets")).json()
    added = await auth_client.post(
        "/v1/progress/entries", json={"day": date.today().isoformat(), "weight_kg": 60}
    )
    assert added.status_code == 201, added.text
    after = (await auth_client.get("/v1/me/targets")).json()
    assert after["bmr_kcal"] < before["bmr_kcal"]
    overview = (await auth_client.get("/v1/progress/overview")).json()
    assert overview["current_weight_kg"] == 60
    assert overview["start_weight_kg"] != 60


async def test_production_refuses_stub_providers(auth_client: AsyncClient, monkeypatch):
    from app.core.config import settings

    await complete_onboarding(auth_client)
    monkeypatch.setattr(settings, "env", "production")
    photo = await auth_client.post(
        "/v1/vision/recognize",
        files={"image": ("meal.jpg", b"\xff\xd8\xff-production-stub", "image/jpeg")},
    )
    assert photo.status_code == 503
    assert "key" not in photo.text.lower()
