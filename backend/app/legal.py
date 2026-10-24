"""Privacy Policy, Terms of Service and the refund policy shown in the app (Settings → Legal). They are served by the
API so they can change without an app release. They describe what this product actually does; have them reviewed by a
lawyer before going live (LEGAL_COMPANY, LEGAL_EMAIL, LEGAL_ADDRESS, LEGAL_UPDATED, REFUND_DAYS)."""

from .config import settings
from .plans import PLAN


def _doc(title: str, intro: str, sections: list[tuple[str, list[str]]], notice: str = "") -> dict:
    return {"title": title, "updated": settings.legal_updated, "intro": intro, "notice": notice,
            "sections": [{"heading": h, "paragraphs": ps} for h, ps in sections]}


def privacy() -> dict:
    co, mail = settings.legal_company, settings.legal_email
    return _doc(
        "Privacy Policy",
        f"This Privacy Policy explains how {co} (\"we\", \"us\") collects, uses and protects personal information when you use the "
        f"{co} app and website (the \"Services\") to manage your business's Google, Facebook and Instagram presence.",
        [
            ("Information we collect", [
                "Account details: your name, mobile number and email address, and the business profiles linked to them.",
                "Business details: business name, address, phone, website, brand voice, keywords, products and the photos and videos you add.",
                "Connected accounts: with your permission (Google and Meta sign-in), your Google Business Profile reviews, posts, photos and "
                "performance numbers, and your Facebook Page / Instagram account so we can post for you. We never see your Google or Meta password.",
                "Payments: plan, amount and status. Card, UPI and bank details are handled by our payment partner (Razorpay); we don't store them.",
                "Usage data: only if you turn on Analytics & Personalisation in Settings.",
            ]),
            ("How we use it", [
                "To provide the Services: draft and publish review replies and posts you approve, upload your photos, and build your reports.",
                "To draft text with AI: the review, post topic and your brand details are sent to our AI provider to write a draft. "
                "Nothing is published without your approval, except where you turn on automatic posting.",
                "To bill you, give support, keep the Services secure, and meet legal obligations.",
            ]),
            ("Sharing", [
                "We share information only with providers that run the Services for us (hosting, AI drafting, SMS, payments), with Google and Meta "
                "when we post for you, and when the law requires it. We don't sell personal information.",
            ]),
            ("Keeping and deleting", [
                "We keep information while your account is active. Settings → Delete Account closes your login at once; your business's data is "
                f"deleted within 30 days unless the law requires us to keep it (for example invoices). You can also write to {mail}.",
                "You can disconnect Google or Meta at any time; we then stop using that access.",
            ]),
            ("Your rights", [
                "Under India's Digital Personal Data Protection Act, 2023 you can ask to see, correct or erase your personal data, withdraw consent, "
                f"and raise a grievance. Write to our Grievance Officer at {mail}; we reply within 30 days.",
            ]),
            ("Security", ["Data travels over HTTPS; Google and Meta tokens are stored encrypted. No system is perfectly secure, and we tell you "
                          "promptly if a breach affects you."]),
            ("Changes", ["We update this policy when the Services change and show the date above. Material changes are announced in the app."]),
            ("Contact", [f"{co}, {settings.legal_address}. Email: {mail}."]),
        ],
        notice="Please read this Privacy Policy carefully. By using the Services you agree to the collection and use of information as "
               "described here. If you do not agree, please do not use the Services.",
    )


def terms() -> dict:
    co, mail = settings.legal_company, settings.legal_email
    return _doc(
        "Terms of Service",
        f"These Terms govern your use of the {co} app and website (the \"Services\"). By creating an account or using the Services you "
        "agree to them.",
        [
            ("1. The Services", ["Tools to manage your business's Google Business Profile, Facebook and Instagram: review replies, AI posts, "
                                 "Google posts and photos, keyword planning and reports. Features depend on your plan."]),
            ("2. Your account", ["Keep your phone and sign-in secure; you're responsible for activity on your account. Business information you "
                                 "give must be accurate, and you must be allowed to manage the business's online profiles."]),
            ("3. Approval of content", ["AI drafts are suggestions. You review and approve what is published (or choose automatic posting where "
                                        "offered) and are responsible for published content. We may decline content that breaks these Terms or "
                                        "Google's or Meta's policies."]),
            ("4. Your content", ["You keep ownership of your photos, text and data, and let us use them only to provide the Services "
                                 "(for example to post them on your profiles)."]),
            ("5. Plans and payment", ["Prices are in Indian Rupees and shown before you pay. Plans are one-time payments for the period shown and "
                                      "don't renew automatically. Refunds follow the Refund Policy in the app."]),
            ("6. Acceptable use", ["Don't use the Services for fake reviews, spam, misleading or unlawful content, to access others' accounts, "
                                   "or to disrupt the Services."]),
            ("7. Third-party services", ["Google, Meta and Razorpay have their own terms. Changes or outages on their side can affect features."]),
            ("8. Disclaimer", ["The Services are provided \"as is\". We work to grow your visibility but don't guarantee specific rankings, "
                               "views, calls or sales."]),
            ("9. Liability", ["To the extent the law allows, our total liability for any claim is limited to the amount you paid us in the "
                              "12 months before the claim, and we aren't liable for indirect or consequential loss."]),
            ("10. Ending", ["You can stop using the Services and delete your account at any time. We may suspend accounts that break these Terms."]),
            ("11. Law", [f"Indian law applies; courts at {settings.legal_address} have jurisdiction."]),
            ("12. Contact", [f"Questions about these Terms: {mail}."]),
        ],
    )


def refund_policy() -> dict:
    days = settings.refund_days
    common = [
        f"Eligible for a refund request within {days} days of purchase, subject to:",
        "If the onboarding/setup of the business profile has been completed, 25% of the paid amount is deducted as onboarding and service charges.",
        "Payment gateway charges of 3% are deducted from the refund amount.",
        "If the GST invoice for the payment has already been filed, the 18% GST amount is deducted as per compliance requirements.",
        "Once a refund is approved, a confirmation email is sent and the amount reaches your account within 5–7 business days, "
        "depending on the bank and payment provider.",
    ]
    included = ["Google Business Profile optimisation with onboarding", "Review replies with SEO keywords, AI posts and Google posts",
                "Photo and video uploads to your Google profile", "Monthly performance reports"]
    plans = []
    for key in ("pro_12", "pro_24", "pro_36"):
        p = PLAN[key]
        plans.append({"key": key, "title": f"{p['months'] // 12} Year{'s' if p['months'] > 12 else ''} Business Growth Plan",
                      "duration": f"{p['months'] // 12} Year{'s' if p['months'] > 12 else ''}", "type": "One-time purchase with manual renewal",
                      "support": "Pro support", "refundable": True, "policy": common, "included": included})
    plans.append({"key": "social_monthly", "title": "Monthly Plan", "duration": "1 month", "type": "One-time payment for a month",
                  "support": "Standard support", "refundable": False,
                  "policy": ["Monthly plans aren't refundable once the month has started; the plan simply ends with the month and nothing "
                             "renews automatically."],
                  "included": included[:3]})
    return {"title": "Refund Policy", "updated": settings.legal_updated, "days": days, "plans": plans}


def ai_usage() -> dict:
    co = settings.legal_company
    return _doc(
        "Terms of AI usage",
        f"{co} uses AI to draft review replies, captions, Google posts and video text for your business.",
        [
            ("What the AI sees", ["The review or topic, your business details, and what you entered in Preference (brand name, story, "
                                  "audience, hashtags). It never sees your passwords or payment details."]),
            ("You stay in control", ["Every draft waits for your approval, except where you turn on automatic posting. You can edit any "
                                     "draft before it goes out, and you're responsible for what you publish."]),
            ("Accuracy", ["AI can make mistakes. It's told to use only facts you gave and never invent prices, offers or claims; check "
                          "drafts before approving. Tell us if something looks wrong and we'll fix the prompt."]),
            ("Providers", ["Drafts are written through our AI provider's business API (OpenAI or Anthropic), only to make the draft you asked for."]),
        ],
    )


DOCS = {"privacy": privacy, "terms": terms, "ai": ai_usage}
