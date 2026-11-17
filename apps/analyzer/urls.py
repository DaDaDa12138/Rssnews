from django.urls import re_path

from apps.analyzer import views

urlpatterns = [
    re_path(r"^$", views.index, name="classifier-index"),
    re_path(r"^save/?$", views.save_classifier, name="classifier-save"),
    re_path(r"^save_all/?$", views.save_all_classifiers, name="classifier-save-all"),
    re_path(r"^(?P<feed_id>\d+)", views.get_classifiers_feed, name="classifier-feed"),
]
