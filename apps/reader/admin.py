from django.contrib import admin

from apps.reader.models import UserSubscription, UserSubscriptionFolders

admin.site.register(UserSubscription)
admin.site.register(UserSubscriptionFolders)
