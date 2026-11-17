"""Reader views package.

The original 4,800 line module was one file. It is now split by feature; this
__init__ keeps every public view available as apps.reader.views.<name> so the
URLconfs and any external imports did not have to change.
"""

from ._base import *  # noqa: F401,F403
from .pages import *  # noqa: F401,F403
from .feeds import *  # noqa: F401,F403
from .stories import *  # noqa: F401,F403
from .read_state import *  # noqa: F401,F403
from .subscriptions import *  # noqa: F401,F403
from .icons import *  # noqa: F401,F403
from .training import *  # noqa: F401,F403
from .starred import *  # noqa: F401,F403
from .rss import *  # noqa: F401,F403
from .dashboards import *  # noqa: F401,F403
from .translate import *  # noqa: F401,F403
from .filters import *  # noqa: F401,F403
from .tags import *  # noqa: F401,F403
from .saved_searches import *  # noqa: F401,F403
from .greader import *  # noqa: F401,F403
from .export import *  # noqa: F401,F403
from .pwa import *  # noqa: F401,F403
