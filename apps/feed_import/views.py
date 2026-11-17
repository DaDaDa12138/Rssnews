"""Feed import views: OPML feed import/export and OAuth-based feed synchronization."""

import datetime

from django.conf import settings
from django.contrib.auth.models import User
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils.translation import gettext
from lxml import etree

from apps.feed_import.models import OPMLExporter, OPMLImporter, UploadedOPML
from apps.feed_import.tasks import ProcessOPML, ProcessOPMLExport
from utils import json_functions as json
from utils import log as logging
from utils.feed_functions import TimeoutError, timelimit
from utils.user_functions import ajax_login_required, get_user
from utils.view_functions import int_argument


@ajax_login_required
def opml_upload(request):
    xml_opml = None
    message = "OK"
    code = 1
    payload = {}

    if request.method == "POST":
        if "file" in request.FILES:
            logging.user(request, "~FR~SBOPML upload starting...")
            file = request.FILES["file"]
            try:
                # UploadedOPML.opml_file is a text column and the import task re-encodes
                # it for lxml, so decode the upload here. Left as bytes, psycopg rejects
                # the row and the failure never looks like a Unicode error.
                xml_opml = file.read().decode("utf-8")
            except UnicodeDecodeError:
                code = -1
                message = "There was a Unicode decode error when reading your OPML file. Ensure it's a text file with a .opml or .xml extension. Is it a zip file?"
            else:
                uploaded_opml = UploadedOPML.objects.create(
                    user_id=request.user.pk,
                    opml_file=xml_opml,
                )
                opml_importer = OPMLImporter(xml_opml.encode("utf-8"), request.user)
                try:
                    feed_count = opml_importer.count_feeds_in_opml()
                except (AttributeError, etree.XMLSyntaxError):
                    code = -1
                    message = "OPML import failed. Couldn't parse XML file."
                else:
                    ProcessOPML.delay(request.user.pk, str(uploaded_opml.pk))
                    logging.user(request, "~FR~SBOPML upload found %s feeds. Tasking..." % feed_count)
                    payload = dict(folders=None, delayed=True, feed_count=feed_count)
                    code = 2
                    message = ""
        else:
            message = "Attach an .opml file."
            code = -1

    return HttpResponse(
        json.encode(dict(message=message, code=code, payload=payload)), content_type="text/html"
    )


@ajax_login_required
def opml_export(request):
    user = get_user(request)
    now = datetime.datetime.now()
    if request.GET.get("user_id") and user.is_staff:
        user_id = int_argument(request.GET, "user_id", None)
        user = User.objects.filter(pk=user_id).first() if user_id else None
        if user is None:
            return HttpResponseBadRequest("Unknown user_id.")

    # Try to export OPML with a 15 second timeout (0.01s in dev for testing)
    timeout_seconds = 0.01 if settings.DEBUG else 15

    @timelimit(timeout_seconds)
    def try_opml_export():
        exporter = OPMLExporter(user)
        opml = exporter.process()
        return exporter, opml

    try:
        exporter, opml = try_opml_export()

        response = HttpResponse(opml, content_type="text/xml; charset=utf-8")
        response["Content-Disposition"] = "attachment; filename=NewsBlur-%s-%s.opml" % (
            user.username,
            now.strftime("%Y-%m-%d"),
        )
        return response

    except TimeoutError:
        # If export takes too long, queue task to email user
        ProcessOPMLExport.delay(user.pk)
        logging.user(user, "~FR~SBOPML export took too long, emailing...")

        # Check if this is an AJAX request
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return HttpResponse(
                json.encode(
                    {
                        "code": 2,
                        "message": gettext(
                            "Your OPML export is being processed. You will receive an email shortly with your subscription backup."
                        ),
                    }
                ),
                content_type="application/json",
            )
        else:
            # Return HTML page for non-AJAX requests
            from django.shortcuts import render

            return render(
                request,
                "reader/opml_export_delayed.xhtml",
                {
                    "user": user,
                },
            )
