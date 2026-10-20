"""Регулярные выражения распознавателей - по темам, как finders/.

Модули берут их через пакет (`from .. import regulars as regs`, `regs.PHONE_RE`), поэтому
все имена тем подняты сюда: где лежит выражение - забота пакета, а не того, кто его зовет.
"""
from .addresses import *  # noqa: F401,F403
from .contacts import *  # noqa: F401,F403
from .details import *  # noqa: F401,F403
from .numbers import *  # noqa: F401,F403
from .orgs import *  # noqa: F401,F403
from .persons import *  # noqa: F401,F403
from .requisites import *  # noqa: F401,F403
from .special import *  # noqa: F401,F403
from .technical import *  # noqa: F401,F403
