from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy

from apps.profile.models import MCustomStyling, blank_authenticate, change_password


class DeleteAccountForm(forms.Form):
    password = forms.CharField(
        widget=forms.PasswordInput(), label=gettext_lazy("Confirm your password"), required=False
    )
    confirm = forms.CharField(
        label=gettext_lazy('Type "Delete" to confirm'), widget=forms.TextInput(), required=False
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super(DeleteAccountForm, self).__init__(*args, **kwargs)

    def clean_password(self):
        user_auth = authenticate(username=self.user.username, password=self.cleaned_data["password"])
        if not user_auth:
            user_auth = blank_authenticate(username=self.user.username)

        if not user_auth:
            raise forms.ValidationError(gettext_lazy("Your password doesn't match."))

        return self.cleaned_data["password"]

    def clean_confirm(self):
        if self.cleaned_data.get("confirm", "").lower() != "delete":
            raise forms.ValidationError(gettext_lazy('Please type "DELETE" to confirm deletion.'))

        return self.cleaned_data["confirm"]


class ForgotPasswordForm(forms.Form):
    email = forms.CharField(
        widget=forms.TextInput(), label=gettext_lazy("Your email address"), required=False
    )

    def __init__(self, *args, **kwargs):
        super(ForgotPasswordForm, self).__init__(*args, **kwargs)

    def clean_email(self):
        if not self.cleaned_data["email"]:
            raise forms.ValidationError(gettext_lazy("Please enter in an email address."))
        try:
            User.objects.get(email__iexact=self.cleaned_data["email"])
        except User.MultipleObjectsReturned:
            pass
        except User.DoesNotExist:
            raise forms.ValidationError(gettext_lazy("No user has that email address."))

        return self.cleaned_data["email"]


class ForgotPasswordReturnForm(forms.Form):
    password = forms.CharField(
        widget=forms.PasswordInput(), label=gettext_lazy("Your new password"), required=False
    )


class AccountSettingsForm(forms.Form):
    use_required_attribute = False
    username = forms.RegexField(
        regex=r"^\w+$",
        max_length=30,
        widget=forms.TextInput(attrs={"class": "NB-input"}),
        label=gettext_lazy("username"),
        required=False,
        error_messages={"invalid": "Your username may only contain letters and numbers."},
    )
    email = forms.EmailField(
        widget=forms.TextInput(attrs={"maxlength": 75, "class": "NB-input"}),
        label=gettext_lazy("email address"),
        required=True,
        error_messages={"required": "Please enter an email."},
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "NB-input"}),
        label=gettext_lazy("password"),
        required=False,
    )
    old_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "NB-input"}),
        label=gettext_lazy("password"),
        required=False,
    )
    custom_js = forms.CharField(
        widget=forms.TextInput(attrs={"class": "NB-input"}), label="custom_js", required=False
    )
    custom_css = forms.CharField(
        widget=forms.TextInput(attrs={"class": "NB-input"}), label="custom_css", required=False
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super(AccountSettingsForm, self).__init__(*args, **kwargs)

    def clean_username(self):
        username = self.cleaned_data["username"]
        return username

    def clean_password(self):
        if not self.cleaned_data["password"]:
            return ""
        return self.cleaned_data["password"]

    def clean_email(self):
        return self.cleaned_data["email"]

    def clean(self):
        username = self.cleaned_data.get("username", "")
        new_password = self.cleaned_data.get("new_password", "")
        old_password = self.cleaned_data.get("old_password", "")
        email = self.cleaned_data.get("email", None)

        if username and self.user.username != username:
            try:
                User.objects.get(username__iexact=username)
            except User.DoesNotExist:
                pass
            else:
                raise forms.ValidationError(
                    gettext_lazy("This username is already taken. Try something different.")
                )

        if self.user.email != email:
            if email and User.objects.filter(email__iexact=email).count():
                raise forms.ValidationError(
                    gettext_lazy(
                        "This email is already being used by another account. Try something different."
                    )
                )

        if old_password or new_password:
            code = change_password(self.user, old_password, new_password, only_check=True)
            if code <= 0:
                raise forms.ValidationError(gettext_lazy("Your old password is incorrect."))

        return self.cleaned_data

    def save(self, profile_callback=None):
        username = self.cleaned_data["username"]
        new_password = self.cleaned_data.get("new_password", None)
        old_password = self.cleaned_data.get("old_password", None)
        email = self.cleaned_data.get("email", None)
        custom_css = self.cleaned_data.get("custom_css", None)
        custom_js = self.cleaned_data.get("custom_js", None)

        if username and self.user.username != username:
            change_password(self.user, self.user.username, username)
            self.user.username = username
            self.user.save()

        self.user.profile.update_email(email)

        if old_password or new_password:
            change_password(self.user, old_password, new_password)

        MCustomStyling.save_user(self.user.pk, custom_css, custom_js)
