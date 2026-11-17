from apps.reader.url_map import build_url_map
from utils.templatetags.utils_tags import current_domain


def url_map(request):
    """Hand the generated route table to base.html, which ships it as NEWSBLUR.URLs."""
    urls = dict(build_url_map())
    urls["domain"] = current_domain()
    return {"newsblur_urls": urls}
