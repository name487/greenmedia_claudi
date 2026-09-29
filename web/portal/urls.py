from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("clients/", views.clients, name="clients"),
    path("clients/template.csv", views.clients_template, name="clients_template"),
    path("clients/<int:client_id>/", views.client_detail, name="client_detail"),
    path("gmb/", views.gmb, name="gmb"),
    path("gmb/google/", views.google_connections, name="google"),
    path("reviews/", views.reviews, name="reviews"),
    path("content/", views.content, name="content"),
    path("creative/", views.creative, name="creative"),
    path("social/", views.social, name="social"),
    path("seo/", views.seo, name="seo"),
    path("analytics/", views.analytics, name="analytics"),
    path("reports/", views.reports, name="reports"),
    path("tasks/", views.tasks, name="tasks"),
    path("settings/", views.settings_view, name="settings"),
]
