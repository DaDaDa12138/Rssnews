from django.urls import re_path

from apps.profile import views
from apps.profile.language import language_preference

urlpatterns = [
    re_path(r"^language/?$", language_preference, name="language-preference"),
    re_path(r"^csp-report/?$", views.csp_report, name="profile-csp-report"),
    re_path(r"^get_preferences?/?", views.get_preference, name="profile-get-preference"),
    re_path(r"^set_preference/?", views.set_preference, name="profile-set-preference"),
    re_path(r"^set_account_settings/?", views.set_account_settings, name="profile-set-account-settings"),
    re_path(r"^set_view_setting/?", views.set_view_setting, name="profile-set-view-setting"),
    re_path(r"^clear_view_setting/?", views.clear_view_setting, name="profile-clear-view-setting"),
    re_path(r"^set_collapsed_folders/?", views.set_collapsed_folders, name="profile-set-collapsed-folders"),
    re_path(r"^delete_account/?", views.delete_account, name="profile-delete-account"),
    re_path(r"^forgot_password_return/?", views.forgot_password_return, name="profile-forgot-password-return"),
    re_path(r"^forgot_password/?", views.forgot_password, name="profile-forgot-password"),
    re_path(r"^delete_starred_stories/?", views.delete_starred_stories, name="profile-delete-starred-stories"),
    re_path(r"^count_starred_stories/?", views.count_starred_stories, name="profile-count-starred-stories"),
    re_path(r"^count_classifiers/?", views.count_classifiers, name="profile-count-classifiers"),
    re_path(r"^storage_usage/?", views.storage_usage, name="profile-storage-usage"),
    re_path(r"^delete_classifiers/?", views.delete_classifiers, name="profile-delete-classifiers"),
    re_path(r"^delete_all_sites/?", views.delete_all_sites, name="profile-delete-all-sites"),
    re_path(
        # Usernames can hold spaces and punctuation that \w+ won't match, which made
        # reverse() raise NoReverseMatch while building unsubscribe links for emails.
        r"^email_optout/(?P<username>[^/]+)/(?P<secret>\w+)/?$",
        views.email_optout_token,
        name="profile-email-optout-token",
    ),
    re_path(r"^email_optout/?", views.email_optout, name="profile-email-optout"),
]
