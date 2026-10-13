"""Curated starter catalogue for the Russian market.

Hand-checked rather than a bulk import: the analysis concluded that curation is the
differentiator against FatSecret's noisy database. The starter set intentionally covers
common Russian staples, inexpensive proteins and enough meal-type alternatives for a
seven-day plan without turning the seed file into an unreviewable food dump.

Nutrients are per 100 g of the edible part. Prices are roubles per kilogram, Moscow
average — replace with a regional feed (Rosstat / OFD receipts) before launch; the
schema versions them so this is a data swap, not a migration.
"""

from __future__ import annotations

from typing import TypedDict


class ProductSeed(TypedDict, total=False):
    slug: str
    name: str
    category: str
    kcal: float
    protein: float
    fat: float
    carbs: float
    fiber: float
    price_per_kg: float
    tags: list[str]
    allergens: list[str]


PRODUCTS: list[ProductSeed] = [
    # --- meat, poultry, fish ---
    {"slug": "chicken_breast", "name": "Куриная грудка, филе", "category": "meat", "kcal": 113, "protein": 23.6, "fat": 1.9, "carbs": 0.4, "price_per_kg": 420, "tags": ["poultry"]},
    {"slug": "chicken_thigh", "name": "Куриное бедро без кости", "category": "meat", "kcal": 185, "protein": 17.0, "fat": 12.0, "carbs": 0.0, "price_per_kg": 380, "tags": ["poultry"]},
    {"slug": "turkey_fillet", "name": "Индейка, филе", "category": "meat", "kcal": 104, "protein": 22.0, "fat": 1.5, "carbs": 0.0, "price_per_kg": 520, "tags": ["poultry"]},
    {"slug": "beef_shoulder", "name": "Говядина, лопатка", "category": "meat", "kcal": 187, "protein": 19.0, "fat": 12.0, "carbs": 0.0, "price_per_kg": 700, "tags": ["meat"]},
    {"slug": "pork_loin", "name": "Свинина, карбонад", "category": "meat", "kcal": 190, "protein": 20.0, "fat": 12.0, "carbs": 0.0, "price_per_kg": 480, "tags": ["meat", "pork"]},
    {"slug": "cod_fillet", "name": "Треска, филе", "category": "fish", "kcal": 78, "protein": 17.7, "fat": 0.7, "carbs": 0.0, "price_per_kg": 550, "tags": ["fish"], "allergens": ["fish"]},
    {"slug": "pink_salmon", "name": "Горбуша", "category": "fish", "kcal": 142, "protein": 20.5, "fat": 6.5, "carbs": 0.0, "price_per_kg": 650, "tags": ["fish"], "allergens": ["fish"]},
    {"slug": "herring", "name": "Сельдь солёная", "category": "fish", "kcal": 160, "protein": 17.0, "fat": 9.0, "carbs": 0.0, "price_per_kg": 300, "tags": ["fish"], "allergens": ["fish"]},
    {"slug": "canned_tuna", "name": "Тунец консервированный в собственном соку", "category": "fish", "kcal": 96, "protein": 21.0, "fat": 1.0, "carbs": 0.0, "price_per_kg": 900, "tags": ["fish"], "allergens": ["fish"]},
    # --- eggs and dairy ---
    {"slug": "egg", "name": "Яйцо куриное", "category": "eggs", "kcal": 157, "protein": 12.7, "fat": 11.5, "carbs": 0.7, "price_per_kg": 240, "tags": ["egg"], "allergens": ["egg"]},
    {"slug": "cottage_cheese_5", "name": "Творог 5%", "category": "dairy", "kcal": 121, "protein": 17.0, "fat": 5.0, "carbs": 1.8, "price_per_kg": 400, "tags": ["dairy"], "allergens": ["lactose"]},
    {"slug": "cottage_cheese_0", "name": "Творог обезжиренный", "category": "dairy", "kcal": 71, "protein": 16.5, "fat": 0.6, "carbs": 1.3, "price_per_kg": 350, "tags": ["dairy"], "allergens": ["lactose"]},
    {"slug": "milk_25", "name": "Молоко 2,5%", "category": "dairy", "kcal": 52, "protein": 2.9, "fat": 2.5, "carbs": 4.7, "price_per_kg": 90, "tags": ["dairy"], "allergens": ["lactose"]},
    {"slug": "kefir_1", "name": "Кефир 1%", "category": "dairy", "kcal": 40, "protein": 3.0, "fat": 1.0, "carbs": 4.0, "price_per_kg": 95, "tags": ["dairy"], "allergens": ["lactose"]},
    {"slug": "yogurt_natural", "name": "Йогурт натуральный 3,2%", "category": "dairy", "kcal": 66, "protein": 4.3, "fat": 3.2, "carbs": 4.5, "price_per_kg": 190, "tags": ["dairy"], "allergens": ["lactose"]},
    {"slug": "cheese_semi_hard", "name": "Сыр полутвёрдый 45%", "category": "dairy", "kcal": 350, "protein": 25.0, "fat": 27.0, "carbs": 0.0, "price_per_kg": 900, "tags": ["dairy"], "allergens": ["lactose"]},
    {"slug": "sour_cream_15", "name": "Сметана 15%", "category": "dairy", "kcal": 158, "protein": 2.6, "fat": 15.0, "carbs": 3.0, "price_per_kg": 250, "tags": ["dairy"], "allergens": ["lactose"]},
    {"slug": "whey_protein", "name": "Протеин сывороточный", "category": "supplements", "kcal": 380, "protein": 75.0, "fat": 6.0, "carbs": 8.0, "price_per_kg": 3000, "tags": ["dairy"], "allergens": ["lactose"]},
    # --- grains and bread ---
    {"slug": "buckwheat", "name": "Гречневая крупа", "category": "grains", "kcal": 343, "protein": 12.6, "fat": 3.3, "carbs": 62.0, "fiber": 10.0, "price_per_kg": 110},
    {"slug": "rice_white", "name": "Рис белый", "category": "grains", "kcal": 344, "protein": 6.7, "fat": 0.7, "carbs": 78.0, "fiber": 1.4, "price_per_kg": 120},
    {"slug": "oats", "name": "Овсяные хлопья", "category": "grains", "kcal": 366, "protein": 11.9, "fat": 7.2, "carbs": 59.0, "fiber": 10.0, "price_per_kg": 100, "allergens": ["gluten"]},
    {"slug": "pasta_durum", "name": "Макароны из твёрдых сортов", "category": "grains", "kcal": 350, "protein": 12.0, "fat": 1.3, "carbs": 70.0, "fiber": 3.0, "price_per_kg": 130, "allergens": ["gluten"]},
    {"slug": "bread_wholegrain", "name": "Хлеб цельнозерновой", "category": "bakery", "kcal": 230, "protein": 8.0, "fat": 3.0, "carbs": 40.0, "fiber": 6.0, "price_per_kg": 180, "allergens": ["gluten"]},
    # --- legumes ---
    {"slug": "lentils", "name": "Чечевица", "category": "legumes", "kcal": 295, "protein": 24.0, "fat": 1.5, "carbs": 46.3, "fiber": 11.0, "price_per_kg": 180},
    {"slug": "chickpeas", "name": "Нут", "category": "legumes", "kcal": 364, "protein": 19.0, "fat": 6.0, "carbs": 61.0, "fiber": 17.0, "price_per_kg": 260},
    {"slug": "beans_canned", "name": "Фасоль консервированная", "category": "legumes", "kcal": 99, "protein": 6.7, "fat": 0.3, "carbs": 17.0, "fiber": 6.0, "price_per_kg": 200},
    # --- vegetables ---
    {"slug": "potato", "name": "Картофель", "category": "vegetables", "kcal": 77, "protein": 2.0, "fat": 0.4, "carbs": 16.0, "fiber": 1.4, "price_per_kg": 45},
    {"slug": "carrot", "name": "Морковь", "category": "vegetables", "kcal": 35, "protein": 1.3, "fat": 0.1, "carbs": 6.9, "fiber": 2.4, "price_per_kg": 50},
    {"slug": "cabbage", "name": "Капуста белокочанная", "category": "vegetables", "kcal": 28, "protein": 1.8, "fat": 0.1, "carbs": 4.7, "fiber": 2.0, "price_per_kg": 40},
    {"slug": "onion", "name": "Лук репчатый", "category": "vegetables", "kcal": 41, "protein": 1.4, "fat": 0.0, "carbs": 8.2, "fiber": 1.7, "price_per_kg": 40},
    {"slug": "cucumber", "name": "Огурец", "category": "vegetables", "kcal": 15, "protein": 0.8, "fat": 0.1, "carbs": 2.5, "fiber": 0.7, "price_per_kg": 160},
    {"slug": "tomato", "name": "Помидор", "category": "vegetables", "kcal": 20, "protein": 1.1, "fat": 0.2, "carbs": 3.7, "fiber": 1.2, "price_per_kg": 200},
    {"slug": "bell_pepper", "name": "Перец болгарский", "category": "vegetables", "kcal": 27, "protein": 1.3, "fat": 0.0, "carbs": 5.3, "fiber": 1.9, "price_per_kg": 300},
    {"slug": "broccoli", "name": "Брокколи замороженная", "category": "vegetables", "kcal": 34, "protein": 2.8, "fat": 0.4, "carbs": 4.0, "fiber": 2.6, "price_per_kg": 320},
    # --- fruit ---
    {"slug": "apple", "name": "Яблоко", "category": "fruit", "kcal": 47, "protein": 0.4, "fat": 0.4, "carbs": 9.8, "fiber": 2.4, "price_per_kg": 130},
    {"slug": "banana", "name": "Банан", "category": "fruit", "kcal": 96, "protein": 1.5, "fat": 0.2, "carbs": 21.0, "fiber": 2.6, "price_per_kg": 130},
    {"slug": "orange", "name": "Апельсин", "category": "fruit", "kcal": 43, "protein": 0.9, "fat": 0.2, "carbs": 8.1, "fiber": 2.2, "price_per_kg": 150},
    # --- fats, nuts, sweeteners ---
    {"slug": "sunflower_oil", "name": "Масло подсолнечное", "category": "fats", "kcal": 899, "protein": 0.0, "fat": 99.9, "carbs": 0.0, "price_per_kg": 150},
    {"slug": "olive_oil", "name": "Масло оливковое", "category": "fats", "kcal": 898, "protein": 0.0, "fat": 99.8, "carbs": 0.0, "price_per_kg": 900},
    {"slug": "butter_82", "name": "Масло сливочное 82,5%", "category": "fats", "kcal": 748, "protein": 0.5, "fat": 82.5, "carbs": 0.8, "price_per_kg": 1100, "tags": ["dairy"], "allergens": ["lactose"]},
    {"slug": "walnuts", "name": "Грецкий орех", "category": "nuts", "kcal": 654, "protein": 15.0, "fat": 65.0, "carbs": 7.0, "fiber": 6.7, "price_per_kg": 1200, "allergens": ["nuts"]},
    {"slug": "peanut_butter", "name": "Арахисовая паста", "category": "nuts", "kcal": 588, "protein": 25.0, "fat": 50.0, "carbs": 20.0, "price_per_kg": 700, "allergens": ["nuts"]},
    {"slug": "honey", "name": "Мёд", "category": "sweeteners", "kcal": 329, "protein": 0.8, "fat": 0.0, "carbs": 81.0, "price_per_kg": 800, "tags": ["honey"]},
    # --- expanded athlete-friendly staples ---
    {"slug": "chicken_liver", "name": "Печень куриная", "category": "meat", "kcal": 136, "protein": 20.4, "fat": 5.9, "carbs": 0.7, "price_per_kg": 260, "tags": ["poultry"]},
    {"slug": "turkey_thigh", "name": "Индейка, бедро без кости", "category": "meat", "kcal": 150, "protein": 19.0, "fat": 8.0, "carbs": 0.0, "price_per_kg": 450, "tags": ["poultry"]},
    {"slug": "lean_beef", "name": "Говядина постная", "category": "meat", "kcal": 158, "protein": 21.0, "fat": 8.0, "carbs": 0.0, "price_per_kg": 760, "tags": ["meat"]},
    {"slug": "pollock", "name": "Минтай, филе", "category": "fish", "kcal": 72, "protein": 15.9, "fat": 0.9, "carbs": 0.0, "price_per_kg": 300, "tags": ["fish"], "allergens": ["fish"]},
    {"slug": "shrimp", "name": "Креветки очищенные", "category": "fish", "kcal": 85, "protein": 20.0, "fat": 1.5, "carbs": 0.0, "price_per_kg": 950, "tags": ["fish"], "allergens": ["fish", "shellfish"]},
    {"slug": "sardines", "name": "Сардины консервированные", "category": "fish", "kcal": 208, "protein": 25.0, "fat": 11.0, "carbs": 0.0, "price_per_kg": 650, "tags": ["fish"], "allergens": ["fish"]},
    {"slug": "skyr", "name": "Скир натуральный", "category": "dairy", "kcal": 63, "protein": 11.0, "fat": 0.2, "carbs": 3.6, "price_per_kg": 450, "tags": ["dairy"], "allergens": ["lactose"]},
    {"slug": "ryazhenka", "name": "Ряженка 4%", "category": "dairy", "kcal": 67, "protein": 2.8, "fat": 4.0, "carbs": 4.2, "price_per_kg": 130, "tags": ["dairy"], "allergens": ["lactose"]},
    {"slug": "mozzarella", "name": "Моцарелла", "category": "dairy", "kcal": 280, "protein": 22.0, "fat": 20.0, "carbs": 2.0, "price_per_kg": 900, "tags": ["dairy"], "allergens": ["lactose"]},
    {"slug": "quinoa", "name": "Киноа", "category": "grains", "kcal": 368, "protein": 14.0, "fat": 6.0, "carbs": 64.0, "fiber": 7.0, "price_per_kg": 500},
    {"slug": "bulgur", "name": "Булгур", "category": "grains", "kcal": 342, "protein": 12.3, "fat": 1.3, "carbs": 76.0, "fiber": 4.5, "price_per_kg": 180, "allergens": ["gluten"]},
    {"slug": "millet", "name": "Пшено", "category": "grains", "kcal": 342, "protein": 11.5, "fat": 3.3, "carbs": 66.5, "fiber": 8.5, "price_per_kg": 100},
    {"slug": "corn_grits", "name": "Кукурузная крупа", "category": "grains", "kcal": 328, "protein": 8.3, "fat": 1.2, "carbs": 71.0, "fiber": 4.8, "price_per_kg": 120},
    {"slug": "rye_bread", "name": "Хлеб ржаной", "category": "bakery", "kcal": 210, "protein": 6.0, "fat": 1.5, "carbs": 40.0, "fiber": 6.0, "price_per_kg": 160, "allergens": ["gluten"]},
    {"slug": "green_peas", "name": "Зелёный горошек замороженный", "category": "legumes", "kcal": 77, "protein": 5.2, "fat": 0.4, "carbs": 13.7, "fiber": 5.0, "price_per_kg": 180},
    {"slug": "tofu", "name": "Тофу натуральный", "category": "plant_protein", "kcal": 76, "protein": 8.0, "fat": 4.8, "carbs": 0.7, "price_per_kg": 500, "tags": ["vegetarian", "vegan"], "allergens": ["soy"]},
    {"slug": "zucchini", "name": "Кабачок", "category": "vegetables", "kcal": 24, "protein": 1.2, "fat": 0.3, "carbs": 4.6, "fiber": 1.0, "price_per_kg": 180},
    {"slug": "eggplant", "name": "Баклажан", "category": "vegetables", "kcal": 24, "protein": 1.2, "fat": 0.1, "carbs": 5.5, "fiber": 3.0, "price_per_kg": 220},
    {"slug": "beet", "name": "Свёкла", "category": "vegetables", "kcal": 43, "protein": 1.6, "fat": 0.2, "carbs": 9.6, "fiber": 2.8, "price_per_kg": 65},
    {"slug": "green_beans", "name": "Стручковая фасоль", "category": "vegetables", "kcal": 31, "protein": 1.8, "fat": 0.2, "carbs": 7.0, "fiber": 3.4, "price_per_kg": 260},
    {"slug": "spinach", "name": "Шпинат замороженный", "category": "vegetables", "kcal": 23, "protein": 2.9, "fat": 0.4, "carbs": 2.0, "fiber": 2.2, "price_per_kg": 350},
    {"slug": "avocado", "name": "Авокадо", "category": "fruit", "kcal": 160, "protein": 2.0, "fat": 14.7, "carbs": 1.8, "fiber": 6.7, "price_per_kg": 500},
    {"slug": "pear", "name": "Груша", "category": "fruit", "kcal": 42, "protein": 0.4, "fat": 0.3, "carbs": 10.3, "fiber": 2.8, "price_per_kg": 170},
    {"slug": "berries_frozen", "name": "Ягодная смесь замороженная", "category": "fruit", "kcal": 45, "protein": 0.7, "fat": 0.3, "carbs": 9.0, "fiber": 4.0, "price_per_kg": 400},
    {"slug": "raisins", "name": "Изюм", "category": "fruit", "kcal": 299, "protein": 3.1, "fat": 0.5, "carbs": 79.0, "fiber": 3.7, "price_per_kg": 300},
    {"slug": "pumpkin_seeds", "name": "Тыквенные семечки", "category": "seeds", "kcal": 559, "protein": 30.0, "fat": 49.0, "carbs": 10.0, "fiber": 6.0, "price_per_kg": 650, "allergens": ["seeds"]},
]


class RecipeSeed(TypedDict, total=False):
    slug: str
    name: str
    meal_types: list[str]
    items: dict[str, float]  # product slug -> grams in one base portion
    prep_minutes: int


RECIPES: list[RecipeSeed] = [
    {"slug": "oats_banana_pb", "name": "Овсянка с бананом и арахисовой пастой", "meal_types": ["breakfast"], "prep_minutes": 10,
     "items": {"oats": 70, "milk_25": 200, "banana": 100, "peanut_butter": 15}},
    {"slug": "cottage_honey_walnut", "name": "Творог с мёдом и грецким орехом", "meal_types": ["breakfast", "snack"], "prep_minutes": 3,
     "items": {"cottage_cheese_5": 200, "honey": 15, "walnuts": 20}},
    {"slug": "omelette_tomato", "name": "Омлет из трёх яиц с помидорами", "meal_types": ["breakfast"], "prep_minutes": 12,
     "items": {"egg": 165, "milk_25": 50, "tomato": 100, "sunflower_oil": 5}},
    {"slug": "oat_pancake_cottage", "name": "Овсяноблин с творогом", "meal_types": ["breakfast"], "prep_minutes": 15,
     "items": {"oats": 50, "egg": 110, "cottage_cheese_0": 100, "sunflower_oil": 5}},
    {"slug": "buckwheat_chicken", "name": "Гречка с куриной грудкой и морковью", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"buckwheat": 90, "chicken_breast": 180, "carrot": 80, "onion": 40, "sunflower_oil": 10}},
    {"slug": "rice_turkey_broccoli", "name": "Рис с индейкой и брокколи", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"rice_white": 90, "turkey_fillet": 170, "broccoli": 150, "olive_oil": 10}},
    {"slug": "pasta_beef_tomato", "name": "Макароны с говядиной и томатами", "meal_types": ["lunch", "dinner"], "prep_minutes": 35,
     "items": {"pasta_durum": 100, "beef_shoulder": 150, "tomato": 120, "onion": 40, "sunflower_oil": 10}},
    {"slug": "cod_potato_veg", "name": "Треска с картофелем и овощами", "meal_types": ["dinner"], "prep_minutes": 30,
     "items": {"cod_fillet": 200, "potato": 200, "carrot": 60, "olive_oil": 10}},
    {"slug": "salmon_rice_cucumber", "name": "Горбуша с рисом и огурцом", "meal_types": ["lunch", "dinner"], "prep_minutes": 25,
     "items": {"pink_salmon": 170, "rice_white": 80, "cucumber": 100, "olive_oil": 8}},
    {"slug": "lentil_soup", "name": "Чечевичный суп с морковью и луком", "meal_types": ["lunch"], "prep_minutes": 40,
     "items": {"lentils": 90, "carrot": 80, "onion": 50, "potato": 100, "sunflower_oil": 10}},
    {"slug": "tuna_egg_salad", "name": "Салат с тунцом, яйцом и овощами", "meal_types": ["lunch", "dinner", "snack"], "prep_minutes": 10,
     "items": {"canned_tuna": 120, "egg": 110, "cucumber": 100, "tomato": 100, "olive_oil": 10}},
    {"slug": "protein_kefir_shake", "name": "Кефир с протеином", "meal_types": ["snack"], "prep_minutes": 2,
     "items": {"kefir_1": 300, "whey_protein": 30, "banana": 80}},
    {"slug": "yogurt_apple", "name": "Йогурт с яблоком", "meal_types": ["snack"], "prep_minutes": 2,
     "items": {"yogurt_natural": 200, "apple": 150}},
    {"slug": "cheese_sandwich", "name": "Бутерброд цельнозерновой с сыром", "meal_types": ["breakfast", "snack"], "prep_minutes": 3,
     "items": {"bread_wholegrain": 60, "cheese_semi_hard": 40, "butter_82": 8, "cucumber": 50}},
    {"slug": "pork_buckwheat_cabbage", "name": "Свинина с гречкой и капустой", "meal_types": ["lunch", "dinner"], "prep_minutes": 35,
     "items": {"pork_loin": 160, "buckwheat": 90, "cabbage": 120, "sunflower_oil": 10}},
    {"slug": "chicken_thigh_potato", "name": "Куриное бедро с картофелем", "meal_types": ["lunch", "dinner"], "prep_minutes": 45,
     "items": {"chicken_thigh": 180, "potato": 220, "onion": 40, "sunflower_oil": 10}},
    {"slug": "chickpea_veg_stew", "name": "Нут тушёный с овощами", "meal_types": ["lunch", "dinner"], "prep_minutes": 40,
     "items": {"chickpeas": 100, "bell_pepper": 100, "tomato": 120, "onion": 50, "olive_oil": 12}},
    {"slug": "herring_potato_onion", "name": "Сельдь с картофелем и луком", "meal_types": ["dinner"], "prep_minutes": 25,
     "items": {"herring": 120, "potato": 220, "onion": 40, "sunflower_oil": 8}},
    {"slug": "milk_banana_smoothie", "name": "Смузи молоко-банан-овсянка", "meal_types": ["breakfast", "snack"], "prep_minutes": 3,
     "items": {"milk_25": 250, "banana": 120, "oats": 40, "honey": 10}},
    {"slug": "cabbage_carrot_salad", "name": "Салат из капусты и моркови", "meal_types": ["lunch", "snack"], "prep_minutes": 8,
     "items": {"cabbage": 150, "carrot": 80, "sunflower_oil": 12}},
    {"slug": "beans_egg_scramble", "name": "Фасоль с яйцом и перцем", "meal_types": ["breakfast", "lunch"], "prep_minutes": 12,
     "items": {"beans_canned": 180, "egg": 110, "bell_pepper": 80, "olive_oil": 8}},
    {"slug": "cottage_orange_snack", "name": "Творог обезжиренный с апельсином", "meal_types": ["snack"], "prep_minutes": 2,
     "items": {"cottage_cheese_0": 180, "orange": 150}},
    # --- expanded breakfasts ---
    {"slug": "buckwheat_egg_tomato", "name": "Гречка с яйцом и томатами", "meal_types": ["breakfast"], "prep_minutes": 15,
     "items": {"buckwheat": 70, "egg": 110, "tomato": 120, "sunflower_oil": 5}},
    {"slug": "millet_cottage_apple", "name": "Пшённая каша с творогом и яблоком", "meal_types": ["breakfast"], "prep_minutes": 20,
     "items": {"millet": 65, "milk_25": 180, "cottage_cheese_0": 100, "apple": 100}},
    {"slug": "corn_porridge_cheese", "name": "Кукурузная каша с сыром", "meal_types": ["breakfast"], "prep_minutes": 18,
     "items": {"corn_grits": 65, "milk_25": 180, "cheese_semi_hard": 30, "butter_82": 5}},
    {"slug": "quinoa_berry_skyr", "name": "Киноа со скиром и ягодами", "meal_types": ["breakfast"], "prep_minutes": 15,
     "items": {"quinoa": 60, "skyr": 160, "berries_frozen": 100, "honey": 10}},
    {"slug": "rye_avocado_egg", "name": "Ржаной тост с авокадо и яйцом", "meal_types": ["breakfast"], "prep_minutes": 10,
     "items": {"rye_bread": 70, "avocado": 70, "egg": 55, "tomato": 100}},
    {"slug": "skyr_banana_seeds", "name": "Скир с бананом и тыквенными семечками", "meal_types": ["breakfast", "snack"], "prep_minutes": 3,
     "items": {"skyr": 220, "banana": 100, "pumpkin_seeds": 15, "honey": 8}},
    {"slug": "tofu_spinach_scramble", "name": "Скрамбл из тофу со шпинатом", "meal_types": ["breakfast"], "prep_minutes": 12,
     "items": {"tofu": 180, "spinach": 100, "tomato": 100, "olive_oil": 8, "rye_bread": 50}},
    {"slug": "cottage_berry_bowl", "name": "Творожная миска с ягодами", "meal_types": ["breakfast", "snack"], "prep_minutes": 3,
     "items": {"cottage_cheese_0": 200, "berries_frozen": 100, "honey": 12, "pumpkin_seeds": 10}},
    {"slug": "tuna_rye_sandwich", "name": "Ржаной сэндвич с тунцом", "meal_types": ["breakfast", "lunch", "snack"], "prep_minutes": 8,
     "items": {"rye_bread": 80, "canned_tuna": 100, "cucumber": 80, "tomato": 80, "sour_cream_15": 20}},
    {"slug": "egg_millet_vegetables", "name": "Пшено с яйцом и овощами", "meal_types": ["breakfast", "lunch"], "prep_minutes": 18,
     "items": {"millet": 70, "egg": 110, "bell_pepper": 80, "onion": 40, "sunflower_oil": 6}},
    # --- expanded lunches and dinners ---
    {"slug": "turkey_quinoa_vegetables", "name": "Индейка с киноа и овощами", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"quinoa": 80, "turkey_fillet": 180, "zucchini": 120, "bell_pepper": 80, "olive_oil": 8}},
    {"slug": "beef_bulgur_eggplant", "name": "Говядина с булгуром и баклажаном", "meal_types": ["lunch", "dinner"], "prep_minutes": 35,
     "items": {"bulgur": 85, "lean_beef": 160, "eggplant": 140, "onion": 40, "sunflower_oil": 8}},
    {"slug": "pollock_potato_beans", "name": "Минтай с картофелем и стручковой фасолью", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"pollock": 220, "potato": 220, "green_beans": 130, "olive_oil": 8}},
    {"slug": "shrimp_rice_vegetables", "name": "Креветки с рисом и овощами", "meal_types": ["lunch", "dinner"], "prep_minutes": 25,
     "items": {"shrimp": 180, "rice_white": 85, "broccoli": 120, "bell_pepper": 80, "olive_oil": 8}},
    {"slug": "liver_buckwheat_onion", "name": "Куриная печень с гречкой", "meal_types": ["lunch", "dinner"], "prep_minutes": 25,
     "items": {"chicken_liver": 180, "buckwheat": 90, "onion": 60, "carrot": 80, "sunflower_oil": 8}},
    {"slug": "turkey_pasta_zucchini", "name": "Паста с индейкой и кабачком", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"pasta_durum": 95, "turkey_thigh": 160, "zucchini": 150, "tomato": 100, "olive_oil": 8}},
    {"slug": "beef_beet_buckwheat", "name": "Говядина со свёклой и гречкой", "meal_types": ["lunch", "dinner"], "prep_minutes": 35,
     "items": {"lean_beef": 160, "buckwheat": 85, "beet": 140, "cabbage": 100, "sunflower_oil": 8}},
    {"slug": "sardine_potato_salad", "name": "Салат с сардинами и картофелем", "meal_types": ["lunch", "dinner"], "prep_minutes": 20,
     "items": {"sardines": 120, "potato": 220, "cucumber": 100, "cabbage": 100, "olive_oil": 8}},
    {"slug": "tofu_bulgur_vegetables", "name": "Тофу с булгуром и овощами", "meal_types": ["lunch", "dinner"], "prep_minutes": 25,
     "items": {"tofu": 200, "bulgur": 85, "eggplant": 100, "tomato": 120, "olive_oil": 8}},
    {"slug": "turkey_bean_chili", "name": "Индейка с фасолью и овощами", "meal_types": ["lunch", "dinner"], "prep_minutes": 35,
     "items": {"turkey_fillet": 170, "beans_canned": 180, "tomato": 150, "bell_pepper": 100, "onion": 50, "olive_oil": 6}},
    {"slug": "pea_chicken_stew", "name": "Курица с зелёным горошком", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"chicken_breast": 180, "green_peas": 160, "potato": 180, "carrot": 70, "sunflower_oil": 8}},
    {"slug": "cabbage_turkey_stew", "name": "Тушёная капуста с индейкой", "meal_types": ["lunch", "dinner"], "prep_minutes": 35,
     "items": {"turkey_thigh": 170, "cabbage": 250, "carrot": 70, "onion": 50, "sunflower_oil": 8}},
    {"slug": "stuffed_pepper_turkey", "name": "Перцы, фаршированные индейкой и рисом", "meal_types": ["lunch", "dinner"], "prep_minutes": 45,
     "items": {"turkey_fillet": 160, "rice_white": 70, "bell_pepper": 180, "tomato": 100, "onion": 40}},
    {"slug": "zucchini_chicken_buckwheat", "name": "Курица с кабачком и гречкой", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"chicken_breast": 180, "zucchini": 180, "buckwheat": 85, "tomato": 100, "olive_oil": 8}},
    {"slug": "eggplant_beef_rice", "name": "Говядина с баклажаном и рисом", "meal_types": ["lunch", "dinner"], "prep_minutes": 35,
     "items": {"lean_beef": 160, "rice_white": 85, "eggplant": 150, "tomato": 120, "sunflower_oil": 8}},
    {"slug": "quinoa_chicken_spinach", "name": "Киноа с курицей и шпинатом", "meal_types": ["lunch", "dinner"], "prep_minutes": 25,
     "items": {"quinoa": 80, "chicken_breast": 180, "spinach": 120, "cucumber": 80, "olive_oil": 8}},
    {"slug": "pollock_bulgur_cabbage", "name": "Минтай с булгуром и капустой", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"pollock": 220, "bulgur": 85, "cabbage": 150, "carrot": 70, "olive_oil": 8}},
    {"slug": "shrimp_quinoa_avocado", "name": "Креветки с киноа и авокадо", "meal_types": ["lunch", "dinner"], "prep_minutes": 20,
     "items": {"shrimp": 170, "quinoa": 75, "avocado": 70, "cucumber": 100, "tomato": 100}},
    {"slug": "lentil_tofu_stew", "name": "Чечевица с тофу и овощами", "meal_types": ["lunch", "dinner"], "prep_minutes": 35,
     "items": {"lentils": 90, "tofu": 160, "tomato": 150, "carrot": 70, "onion": 50, "olive_oil": 8}},
    {"slug": "tofu_rice_broccoli", "name": "Тофу с рисом и брокколи", "meal_types": ["lunch", "dinner"], "prep_minutes": 25,
     "items": {"tofu": 200, "rice_white": 85, "broccoli": 180, "carrot": 70, "olive_oil": 8}},
    {"slug": "chickpea_beet_salad", "name": "Салат из нута и свёклы", "meal_types": ["lunch", "dinner"], "prep_minutes": 15,
     "items": {"chickpeas": 100, "beet": 160, "cabbage": 120, "cucumber": 100, "olive_oil": 10}},
    {"slug": "sardine_rye_salad", "name": "Ржаной салат с сардинами", "meal_types": ["lunch", "dinner", "snack"], "prep_minutes": 10,
     "items": {"sardines": 100, "rye_bread": 70, "cucumber": 100, "tomato": 100, "sour_cream_15": 20}},
    {"slug": "liver_potato_spinach", "name": "Куриная печень с картофелем и шпинатом", "meal_types": ["lunch", "dinner"], "prep_minutes": 25,
     "items": {"chicken_liver": 180, "potato": 220, "spinach": 100, "onion": 50, "sunflower_oil": 8}},
    {"slug": "turkey_buckwheat_beans", "name": "Индейка с гречкой и стручковой фасолью", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"turkey_fillet": 180, "buckwheat": 90, "green_beans": 150, "carrot": 70, "olive_oil": 8}},
    {"slug": "beef_pasta_spinach", "name": "Паста с говядиной и шпинатом", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"lean_beef": 160, "pasta_durum": 95, "spinach": 120, "tomato": 120, "olive_oil": 8}},
    {"slug": "pollock_rice_cabbage", "name": "Минтай с рисом и капустой", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"pollock": 220, "rice_white": 85, "cabbage": 160, "carrot": 70, "sunflower_oil": 8}},
    {"slug": "tofu_cabbage_stew", "name": "Тофу с тушёной капустой", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"tofu": 200, "cabbage": 250, "carrot": 70, "onion": 50, "sunflower_oil": 8}},
    {"slug": "chicken_quinoa_vegetables", "name": "Курица с киноа и овощами", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"chicken_thigh": 170, "quinoa": 80, "zucchini": 120, "bell_pepper": 80, "olive_oil": 8}},
    {"slug": "turkey_millet_vegetables", "name": "Индейка с пшеном и овощами", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"turkey_fillet": 180, "millet": 85, "broccoli": 130, "carrot": 70, "olive_oil": 8}},
    {"slug": "beef_corn_grits_veg", "name": "Говядина с кукурузной кашей", "meal_types": ["lunch", "dinner"], "prep_minutes": 35,
     "items": {"lean_beef": 160, "corn_grits": 85, "tomato": 120, "bell_pepper": 100, "sunflower_oil": 8}},
    {"slug": "chicken_liver_rice_beet", "name": "Печень с рисом и свёклой", "meal_types": ["lunch", "dinner"], "prep_minutes": 30,
     "items": {"chicken_liver": 180, "rice_white": 85, "beet": 150, "cabbage": 100, "sunflower_oil": 8}},
    # --- expanded snacks ---
    {"slug": "skyr_berries", "name": "Скир с ягодами", "meal_types": ["snack"], "prep_minutes": 2,
     "items": {"skyr": 220, "berries_frozen": 120, "honey": 8}},
    {"slug": "ryazhenka_pear", "name": "Ряженка с грушей", "meal_types": ["snack"], "prep_minutes": 2,
     "items": {"ryazhenka": 250, "pear": 150}},
    {"slug": "cottage_raisins", "name": "Творог с изюмом", "meal_types": ["snack"], "prep_minutes": 2,
     "items": {"cottage_cheese_5": 180, "raisins": 25}},
    {"slug": "pumpkin_kefir_banana", "name": "Кефир с бананом и семечками", "meal_types": ["snack"], "prep_minutes": 3,
     "items": {"kefir_1": 250, "banana": 100, "pumpkin_seeds": 15}},
    {"slug": "mozzarella_tomato_rye", "name": "Моцарелла с томатами и ржаным хлебом", "meal_types": ["snack", "breakfast"], "prep_minutes": 5,
     "items": {"mozzarella": 80, "tomato": 150, "rye_bread": 60}},
    {"slug": "avocado_egg_toast", "name": "Тост с авокадо и яйцом", "meal_types": ["snack", "breakfast"], "prep_minutes": 8,
     "items": {"rye_bread": 60, "avocado": 60, "egg": 55}},
    {"slug": "protein_berry_bowl", "name": "Протеиновая миска с ягодами", "meal_types": ["snack"], "prep_minutes": 3,
     "items": {"skyr": 180, "whey_protein": 20, "berries_frozen": 100, "honey": 8}},
    {"slug": "cottage_banana", "name": "Творог с бананом", "meal_types": ["snack"], "prep_minutes": 2,
     "items": {"cottage_cheese_0": 180, "banana": 100, "pumpkin_seeds": 10}},
    {"slug": "yogurt_pear_seeds", "name": "Йогурт с грушей и семечками", "meal_types": ["snack"], "prep_minutes": 2,
     "items": {"yogurt_natural": 200, "pear": 120, "pumpkin_seeds": 12}},
    {"slug": "milk_raisin_oat_snack", "name": "Молоко с овсяными хлопьями и изюмом", "meal_types": ["snack"], "prep_minutes": 5,
     "items": {"milk_25": 250, "oats": 35, "raisins": 15}},
]
