// Typed views over the API's JSON. Aggregate endpoints (dashboard, analytics, SEO) stay as maps.

DateTime? parseDate(Object? v) => v == null ? null : DateTime.tryParse(v as String)?.toLocal();

class Me {
  Me.fromJson(Map<String, dynamic> j)
      : id = j['id'] as int,
        name = j['name'] as String,
        email = j['email'] as String,
        role = j['role'] as String,
        roleLabel = j['role_label'] as String,
        clientId = j['client_id'] as int?,
        clientName = j['client_name'] as String?,
        sections = List<String>.from(j['sections'] as List),
        permissions = List<String>.from(j['permissions'] as List);

  final int id;
  final String name, email, role, roleLabel;
  final int? clientId;
  final String? clientName;
  final List<String> sections, permissions;

  bool get isClient => clientId != null;
  bool sees(String section) => sections.contains(section);
  bool can(String action) => permissions.contains(action);
}

class ClientBrief {
  ClientBrief.fromJson(Map<String, dynamic> j)
      : id = j['id'] as int,
        companyName = j['company_name'] as String,
        industry = j['industry'] as String? ?? '',
        city = j['city'] as String? ?? '',
        status = j['status'] as String,
        plan = j['plan'] as String,
        rating = (j['rating'] as num?)?.toDouble() ?? 0,
        gmbConnected = j['gmb_connected'] as bool? ?? false,
        pendingReviews = j['pending_reviews'] as int? ?? 0;

  final int id;
  final String companyName, industry, city, status, plan;
  final double rating;
  final bool gmbConnected;
  final int pendingReviews;
}

class Review {
  Review.fromJson(Map<String, dynamic> j)
      : id = j['id'] as int,
        clientId = j['client_id'] as int,
        clientName = j['client_name'] as String,
        author = j['author'] as String,
        rating = j['rating'] as int,
        text = j['text'] as String,
        language = j['language'] as String,
        sentiment = j['sentiment'] as String,
        reply = j['reply'] as String?,
        replyStatus = j['reply_status'] as String,
        needsEscalation = j['needs_escalation'] as bool,
        isSample = j['is_sample'] as bool? ?? false,
        createdAt = parseDate(j['created_at']),
        publishedAt = parseDate(j['published_at']);

  final int id, clientId, rating;
  final String clientName, author, text, language, sentiment, replyStatus;
  final String? reply;
  final bool needsEscalation, isSample;
  final DateTime? createdAt, publishedAt;
}

class Variant {
  Variant({required this.platform, required this.copy, required this.format});
  Variant.fromJson(Map<String, dynamic> j)
      : platform = j['platform'] as String,
        copy = j['copy'] as String,
        format = j['format'] as String;

  final String platform, format;
  String copy;

  Map<String, dynamic> toJson() => {'platform': platform, 'copy': copy, 'format': format};
}

class ContentItem {
  ContentItem.fromJson(Map<String, dynamic> j)
      : id = j['id'] as int,
        clientId = j['client_id'] as int,
        clientName = j['client_name'] as String,
        topic = j['topic'] as String,
        contentType = j['content_type'] as String,
        masterCopy = j['master_copy'] as String? ?? '',
        status = j['status'] as String,
        scheduledAt = parseDate(j['scheduled_at']),
        variants = [for (final v in j['variants'] as List) Variant.fromJson(v as Map<String, dynamic>)];

  final int id, clientId;
  final String clientName, topic, contentType, masterCopy, status;
  final DateTime? scheduledAt;
  final List<Variant> variants;
}

class TaskItem {
  TaskItem.fromJson(Map<String, dynamic> j)
      : id = j['id'] as int,
        clientName = j['client_name'] as String?,
        assigneeName = j['assignee_name'] as String?,
        title = j['title'] as String,
        priority = j['priority'] as String,
        dueDate = j['due_date'] == null ? null : DateTime.tryParse(j['due_date'] as String),
        status = j['status'] as String;

  final int id;
  final String? clientName, assigneeName;
  final String title, priority, status;
  final DateTime? dueDate;
}

class ReportItem {
  ReportItem.fromJson(Map<String, dynamic> j)
      : id = j['id'] as int,
        clientName = j['client_name'] as String,
        periodStart = DateTime.parse(j['period_start'] as String),
        periodEnd = DateTime.parse(j['period_end'] as String),
        summary = j['summary'] as String,
        source = j['source'] as String,
        deliveredVia = j['delivered_via'] as String?;

  final int id;
  final String clientName, summary, source;
  final DateTime periodStart, periodEnd;
  final String? deliveredVia;
}

const platformLabels = {
  'gmb': 'Google Business',
  'facebook': 'Facebook',
  'instagram': 'Instagram',
  'linkedin': 'LinkedIn',
  'youtube': 'YouTube',
  'x': 'X',
};

/// Answer to POST /api/auth/otp/request.
class OtpSent {
  OtpSent.fromJson(Map<String, dynamic> j)
      : phone = j['phone'] as String,
        masked = j['masked'] as String,
        length = j['length'] as int,
        resendIn = j['resend_in'] as int,
        devCode = j['dev_code'] as String?;

  final String phone, masked;
  final int length, resendIn;

  /// Only on demo servers without an SMS provider.
  final String? devCode;
}

/// One account the verified phone number can open (POST /api/auth/otp/verify).
class LoginProfile {
  LoginProfile.fromJson(Map<String, dynamic> j)
      : userId = j['user_id'] as int,
        title = j['title'] as String,
        subtitle = j['subtitle'] as String? ?? '',
        kind = j['kind'] as String,
        roleLabel = j['role_label'] as String? ?? '',
        group = j['group'] as String,
        googleState = (j['google'] as Map<String, dynamic>?)?['state'] as String?;

  final int userId;
  final String title, subtitle, kind, roleLabel, group;

  /// connected | approval_pending | needs_google — null for agency profiles.
  final String? googleState;

  bool get needsGoogle => googleState == 'needs_google';
}

class OtpVerified {
  OtpVerified.fromJson(Map<String, dynamic> j)
      : otpToken = j['otp_token'] as String,
        phone = j['phone'] as String,
        profiles = [for (final p in j['profiles'] as List) LoginProfile.fromJson(p as Map<String, dynamic>)];

  final String otpToken, phone;
  final List<LoginProfile> profiles;
}
