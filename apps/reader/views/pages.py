"""Landing pages, authentication and redirects.

Split from apps/reader/views.py; see apps/reader/views/__init__.py.
"""

from ._base import *  # noqa: F401,F403



@never_cache
@ensure_csrf_cookie
@render_to("reader/dashboard.xhtml")
def index(request, **kwargs):
    if request.user.is_anonymous:
        return welcome(request, **kwargs)
    else:
        return dashboard(request, **kwargs)



def dashboard(request, **kwargs):
    """The signed-in shell: the feed list plus the dashboard modules in the splash.

    The personal edition has no social graph, no billing and no recommendation
    queue, so the dashboard only needs the user's rivers, their custom styling
    and their preferences.
    """
    user = request.user
    custom_styling = MCustomStyling.get_user(user.pk)
    dashboard_rivers = MDashboardRiver.get_user_rivers(user.pk)
    preferences = json.decode(user.profile.preferences)

    logging.user(request, "~FBLoading dashboard")

    return {
        "user_profile": user.profile,
        "preferences": preferences,
        "custom_styling": custom_styling,
        "dashboard_rivers": dashboard_rivers,
        "account_images": list(range(1, 4)),
        "debug": settings.DEBUG,
        "debug_assets": settings.DEBUG_ASSETS,
    }, "reader/dashboard.xhtml"



@ensure_csrf_cookie
@render_to("reader/dashboard.xhtml")
def welcome_req(request, **kwargs):
    return welcome(request, **kwargs)



def welcome(request, **kwargs):
    user = get_user(request)
    if request.method == "POST":
        # views.py tells the two welcome forms apart by their fields, since the button label is translated.
        if "login-username" in request.POST:
            login_form = LoginForm(request.POST, prefix="login")
            signup_form = SignupForm(prefix="signup")
        else:
            signup_form = SignupForm(request.POST, prefix="signup")
            return {"form": signup_form}, "accounts/signup.html"
    else:
        login_form = LoginForm(prefix="login")
        signup_form = SignupForm(prefix="signup")

    logging.user(request, "~FBLoading welcome")

    return {
        "user_profile": hasattr(user, "profile") and user.profile,
        "login_form": login_form,
        "signup_form": signup_form,
        "post_request": request.method == "POST",
    }, "reader/welcome.xhtml"



@never_cache
def login(request):
    code = -1
    message = ""
    if request.method == "POST":
        form = LoginForm(request.POST, prefix="login")
        if form.is_valid():
            login_user(request, form.get_user(), backend="django.contrib.auth.backends.ModelBackend")
            if request.POST.get("api"):
                logging.user(form.get_user(), "~FG~BB~SKiPhone Login~FW")
                code = 1
            else:
                logging.user(form.get_user(), "~FG~BBLogin~FW")
                next_url = request.POST.get("next", "")
                if next_url:
                    return HttpResponseRedirect(next_url)
                return HttpResponseRedirect(reverse("index"))
        else:
            message = list(form.errors.items())[0][1][0]

    if request.POST.get("api"):
        return HttpResponse(json.encode(dict(code=code, message=message)), content_type="application/json")
    else:
        return index(request)



@never_cache
@ensure_csrf_cookie
@render_to("accounts/signup.html")
def signup(request):
    if request.method == "POST":
        if settings.ENFORCE_SIGNUP_CAPTCHA:
            signup_form = SignupForm(request.POST, prefix="signup")
            return {"form": signup_form}

        form = SignupForm(prefix="signup", data=request.POST)
        if form.is_valid():
            new_user = form.save(request=request)
            login_user(request, new_user, backend="django.contrib.auth.backends.ModelBackend")
            logging.user(new_user, "~FG~SB~BBNEW SIGNUP: ~FW%s" % new_user.email)

            if not new_user.is_active:
                url = "https://%s%s" % (Site.objects.get_current().domain, reverse("stripe-form"))
                return HttpResponseRedirect(url)
            else:
                return HttpResponseRedirect(reverse("index"))

    # GET: show signup form, with referrer/gift context if present
    referrer_username = request.GET.get("ref") or request.COOKIES.get("nb_referrer")
    gift_code = request.GET.get("gift") or request.COOKIES.get("nb_gift_code")
    form = SignupForm(prefix="signup")

    return {
        "form": form,
        "referrer": referrer_username,
        "gift_code": gift_code,
    }



@never_cache
def logout(request):
    logging.user(request, "~FG~BBLogout~FW")
    logout_user(request)

    if request.GET.get("api"):
        return HttpResponse(json.encode(dict(code=1)), content_type="application/json")
    else:
        return HttpResponseRedirect(reverse("index"))



def autologin(request, username, secret):
    next = request.GET.get("next", "")

    if not username or not secret:
        return HttpResponseForbidden()

    profile = Profile.objects.filter(user__username=username, secret_token=secret)
    if not profile:
        return HttpResponseForbidden()

    user = profile[0].user
    user.backend = settings.AUTHENTICATION_BACKENDS[0]
    login_user(request, user, backend="django.contrib.auth.backends.ModelBackend")
    logging.user(user, "~FG~BB~SKAuto-Login. Next stop: %s~FW" % (next if next else "Homepage",))

    if next and not next.startswith("/"):
        next = "?next=" + next
        return HttpResponseRedirect(reverse("index") + next)
    elif next:
        return HttpResponseRedirect(next)
    else:
        return HttpResponseRedirect(reverse("index"))



def dev_autologin(request, username=None):
    """
    Development-only autologin endpoint. ONLY works in local dev environment.
    Requires both DEBUG=True AND 'localhost' in NEWSBLUR_URL.

    Usage:
        /reader/dev/autologin/           - Login as DEV_AUTOLOGIN_USERNAME
        /reader/dev/autologin/<username>/ - Login as specific user

    apps/reader/views.py: the LAN edition lives on a private address, so a private
    host counts as local development alongside localhost/127.0.0.1.
    """
    host = request.get_host().split(":")[0]
    is_local_dev = settings.DEBUG and (
        host in ("localhost", "127.0.0.1", "[::1]")
        or host.startswith("192.168.")
        or host.startswith("10.")
        or host.startswith("172.")
    )
    if not is_local_dev:
        return HttpResponseForbidden("Dev autologin only available in local development")

    next_url = request.GET.get("next", "")

    if not username:
        username = getattr(settings, "DEV_AUTOLOGIN_USERNAME", None)
        if not username:
            return HttpResponseForbidden("No username provided and DEV_AUTOLOGIN_USERNAME not set")

    try:
        user = User.objects.get(username__iexact=username)
    except User.DoesNotExist:
        return HttpResponseForbidden(f"User '{username}' not found")

    user.backend = settings.AUTHENTICATION_BACKENDS[0]
    login_user(request, user, backend="django.contrib.auth.backends.ModelBackend")
    logging.user(user, "~FG~BB~SK[DEV] Auto-Login. Next: %s~FW" % (next_url or "Homepage"))

    if next_url and not next_url.startswith("/"):
        return HttpResponseRedirect(reverse("index") + "?next=" + next_url)
    elif next_url:
        return HttpResponseRedirect(next_url)
    return HttpResponseRedirect(reverse("index"))



def iframe_buster(request):
    logging.user(request, "~FB~SBiFrame bust!")
    return HttpResponse(status=204)
