import 'api_client.dart';

/// Subscription status from `GET /v1/me/subscription` — the only thing the app
/// uses to decide whether its features are available.
class SubscriptionStatus {
  const SubscriptionStatus({
    required this.state,
    required this.serverHasAccess,
    required this.tier,
    required this.accessUntil,
    required this.message,
  });

  factory SubscriptionStatus.fromJson(Map<String, dynamic> json) =>
      SubscriptionStatus(
        state: json['state']?.toString() ?? 'trial_ended',
        serverHasAccess: json['has_access'] == true,
        tier: json['tier']?.toString(),
        accessUntil: DateTime.tryParse(
          json['access_until']?.toString() ?? '',
        )?.toLocal(),
        message: json['message']?.toString(),
      );

  /// trial | active | trial_ended | expired | revoked
  final String state;
  final bool serverHasAccess;
  final String? tier;
  final DateTime? accessUntil;
  final String? message;

  /// Access as of now. A cached answer read offline still ends at
  /// `access_until`, so being offline never extends a subscription.
  bool get hasAccess {
    if (!serverHasAccess) return false;
    final until = accessUntil;
    return until == null || until.isAfter(DateTime.now());
  }

  bool get isTrial => state == 'trial';

  int? get daysLeft {
    final until = accessUntil;
    if (until == null) return null;
    final hours = until.difference(DateTime.now()).inHours;
    return hours <= 0 ? 0 : (hours / 24).ceil();
  }

  String get title => switch (hasAccess ? state : _blockedState) {
    'trial' => 'Пробный период',
    'active' => 'Подписка ${tier?.toUpperCase() ?? ''}'.trim(),
    'trial_ended' => 'Пробный период закончился',
    'revoked' => 'Подписка отменена',
    _ => 'Подписка закончилась',
  };

  /// A paid or trial period that ran out while cached reads as ended.
  String get _blockedState => switch (state) {
    'trial' || 'trial_ended' => 'trial_ended',
    'revoked' => 'revoked',
    _ => 'expired',
  };

  String get blockedMessage => switch (_blockedState) {
    'trial_ended' =>
      'Пробный период закончился. Оформите подписку, чтобы продолжить.',
    'revoked' => 'Подписка отменена. Оформите подписку, чтобы продолжить.',
    _ => 'Подписка закончилась. Продлите её, чтобы продолжить.',
  };

  String get untilLabel {
    final until = accessUntil;
    if (until == null) return '';
    return '${until.day.toString().padLeft(2, '0')}.'
        '${until.month.toString().padLeft(2, '0')}.${until.year}';
  }
}

Future<SubscriptionStatus> fetchSubscription(ApiClient api) async =>
    SubscriptionStatus.fromJson(await api.get('/v1/me/subscription'));
