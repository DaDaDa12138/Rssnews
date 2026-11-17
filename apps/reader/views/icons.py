"""Custom feed and folder icon uploads.

Split from apps/reader/views.py; see apps/reader/views/__init__.py.
"""

from ._base import *  # noqa: F401,F403

ICON_TYPES = {"upload", "preset", "emoji", "none"}
ICON_SETS = {"lucide", "heroicons-solid"}
ICON_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
ICON_NAME_RE = re.compile(r"^[a-z0-9-]+$")
MAX_ICON_DATA_LENGTH = 120000
MAX_EMOJI_LENGTH = 16
MAX_ICON_UPLOAD_BYTES = 5 * 1024 * 1024
ICON_UPLOAD_FORMATS = {"PNG", "JPEG", "GIF", "WEBP"}




def _clean_icon_payload(icon_type, icon_data, icon_color, icon_set):
    icon_type = (icon_type or "none").strip()
    icon_color = icon_color.strip() if icon_color else None
    icon_set = icon_set.strip() if icon_set else None

    if icon_type not in ICON_TYPES:
        return None, "Invalid icon type"

    if icon_color and not ICON_COLOR_RE.match(icon_color):
        return None, "Invalid icon color"

    if icon_type == "none":
        payload = {"icon_type": "none", "icon_data": None, "icon_color": None, "icon_set": None}
        return payload, None

    if icon_type == "preset":
        if not icon_data:
            return None, "Icon name required"
        if not ICON_NAME_RE.match(icon_data):
            return None, "Invalid icon name"
        icon_set = icon_set or "lucide"
        if icon_set not in ICON_SETS:
            return None, "Invalid icon set"
        payload = {
            "icon_type": icon_type,
            "icon_data": icon_data,
            "icon_color": icon_color,
            "icon_set": icon_set,
        }
        return payload, None

    if icon_type == "emoji":
        if not icon_data:
            return None, "Emoji required"
        if len(icon_data) > MAX_EMOJI_LENGTH:
            return None, "Emoji is too long"
        payload = {"icon_type": icon_type, "icon_data": icon_data, "icon_color": None, "icon_set": None}
        return payload, None

    if icon_type == "upload":
        if not icon_data:
            return None, "Icon data required"
        if len(icon_data) > MAX_ICON_DATA_LENGTH:
            return None, "Icon data is too large"
        payload = {"icon_type": icon_type, "icon_data": icon_data, "icon_color": None, "icon_set": None}
        return payload, None

    return None, "Invalid icon type"



def _process_icon_upload(photo):
    from io import BytesIO

    from PIL import Image

    if photo.size > MAX_ICON_UPLOAD_BYTES:
        return None, "Image must be smaller than 5MB"

    photo_body = photo.read()
    if len(photo_body) > MAX_ICON_UPLOAD_BYTES:
        return None, "Image must be smaller than 5MB"

    try:
        image_file = BytesIO(photo_body)
        image = Image.open(image_file)
        image.verify()
        image_file.seek(0)
        image = Image.open(image_file)
    except Exception:
        return None, "Invalid image file"

    if image.format not in ICON_UPLOAD_FORMATS:
        return None, "Invalid image format"

    if image.mode not in ("RGBA", "RGB"):
        image = image.convert("RGBA")

    image.thumbnail((128, 128), Image.LANCZOS)

    canvas = Image.new("RGBA", (128, 128), (255, 255, 255, 0))
    offset = ((128 - image.width) // 2, (128 - image.height) // 2)
    canvas.paste(image, offset)

    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    icon_data = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return icon_data, None



@ajax_login_required
@json.json_view
def save_folder_icon(request):
    """Save a folder icon (upload, preset, emoji, or remove)"""
    folder_title = request.POST.get("folder_title", "").replace("river:", "")
    icon_type = request.POST.get("icon_type", "none")  # upload, preset, emoji, none
    icon_data = request.POST.get("icon_data")  # base64, icon name, or emoji
    icon_color = request.POST.get("icon_color")  # hex color
    icon_set = request.POST.get("icon_set", "lucide")  # lucide, heroicons-solid

    if not folder_title:
        return {"code": -1, "message": gettext("Folder title required")}

    icon_payload, error_message = _clean_icon_payload(icon_type, icon_data, icon_color, icon_set)
    if error_message:
        return {"code": -1, "message": error_message}

    icon_type = icon_payload["icon_type"]
    icon_data = icon_payload["icon_data"]
    icon_color = icon_payload["icon_color"]
    icon_set = icon_payload["icon_set"]

    if icon_type == "none":
        MFolderIcon.delete_folder_icon(request.user.pk, folder_title)
        logging.user(request, "~FRRemoving folder icon: ~SB%s" % folder_title)
    else:
        MFolderIcon.save_folder_icon(
            request.user.pk,
            folder_title,
            icon_type,
            icon_data,
            icon_color,
            icon_set,
        )
        logging.user(request, "~FBSaving folder icon: ~SB%s (%s)" % (folder_title, icon_type))

    folder_icons = MFolderIcon.get_folder_icons_for_user(request.user.pk)
    return {
        "code": 1,
        "folder_icons": {fi.folder_title: fi.to_json() for fi in folder_icons},
    }



@ajax_login_required
@json.json_view
def upload_folder_icon(request):
    """Handle file upload for custom folder icons"""
    folder_title = request.POST.get("folder_title", "").replace("river:", "")
    photo = request.FILES.get("photo")

    if not folder_title or not photo:
        return {"code": -1, "message": gettext("Folder title and photo required")}

    try:
        icon_data, error_message = _process_icon_upload(photo)
        if error_message:
            return {"code": -1, "message": error_message}

        MFolderIcon.save_folder_icon(
            request.user.pk,
            folder_title,
            icon_type="upload",
            icon_data=icon_data,
            icon_color=None,
        )

        logging.user(request, "~FC~BM~SBUploading folder icon: %s" % folder_title)

        folder_icons = MFolderIcon.get_folder_icons_for_user(request.user.pk)
        return {
            "code": 1,
            "icon_data": icon_data,
            "folder_icons": {fi.folder_title: fi.to_json() for fi in folder_icons},
        }
    except Exception as e:
        logging.user(request, "~FRFolder icon upload error: %s" % e)
        return {"code": -1, "message": gettext("Invalid image file")}



@ajax_login_required
@json.json_view
def save_feed_icon(request):
    """Save a custom feed icon (upload, preset, emoji, or remove)"""
    feed_id = request.POST.get("feed_id")
    icon_type = request.POST.get("icon_type", "none")  # upload, preset, emoji, none
    icon_data = request.POST.get("icon_data")  # base64, icon name, or emoji
    icon_color = request.POST.get("icon_color")  # hex color
    icon_set = request.POST.get("icon_set", "lucide")  # lucide, heroicons-solid

    if not feed_id:
        return {"code": -1, "message": gettext("Feed ID required")}

    try:
        feed_id = int(feed_id)
    except (ValueError, TypeError):
        return {"code": -1, "message": gettext("Invalid feed ID")}

    icon_payload, error_message = _clean_icon_payload(icon_type, icon_data, icon_color, icon_set)
    if error_message:
        return {"code": -1, "message": error_message}

    icon_type = icon_payload["icon_type"]
    icon_data = icon_payload["icon_data"]
    icon_color = icon_payload["icon_color"]
    icon_set = icon_payload["icon_set"]

    if icon_type == "none":
        MCustomFeedIcon.delete_feed_icon(request.user.pk, feed_id)
        logging.user(request, "~FRRemoving feed icon: ~SB%s" % feed_id)
    else:
        MCustomFeedIcon.save_feed_icon(
            request.user.pk,
            feed_id,
            icon_type,
            icon_data,
            icon_color,
            icon_set,
        )
        logging.user(request, "~FBSaving feed icon: ~SB%s (%s)" % (feed_id, icon_type))

    feed_icons = MCustomFeedIcon.get_feed_icons_for_user(request.user.pk)
    return {
        "code": 1,
        "feed_icons": {str(fi.feed_id): fi.to_json() for fi in feed_icons},
    }



@ajax_login_required
@json.json_view
def upload_feed_icon(request):
    """Handle file upload for custom feed icons"""
    feed_id = request.POST.get("feed_id")
    photo = request.FILES.get("photo")

    if not feed_id or not photo:
        return {"code": -1, "message": gettext("Feed ID and photo required")}

    try:
        feed_id = int(feed_id)
    except (ValueError, TypeError):
        return {"code": -1, "message": gettext("Invalid feed ID")}

    try:
        icon_data, error_message = _process_icon_upload(photo)
        if error_message:
            return {"code": -1, "message": error_message}

        MCustomFeedIcon.save_feed_icon(
            request.user.pk,
            feed_id,
            icon_type="upload",
            icon_data=icon_data,
            icon_color=None,
        )

        logging.user(request, "~FC~BM~SBUploading feed icon: %s" % feed_id)

        feed_icons = MCustomFeedIcon.get_feed_icons_for_user(request.user.pk)
        return {
            "code": 1,
            "icon_data": icon_data,
            "feed_icons": {str(fi.feed_id): fi.to_json() for fi in feed_icons},
        }
    except Exception as e:
        logging.user(request, "~FRFeed icon upload error: %s" % e)
        return {"code": -1, "message": gettext("Invalid image file")}
