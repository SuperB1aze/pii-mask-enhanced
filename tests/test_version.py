"""`pii-mask where` - откуда на самом деле работает код.

Нужна потому, что путь до бинаря ничего не говорит о том, какой экземпляр он
импортирует, а разошлись они на этой машине дважды: служба месяц работала из
удаленного каталога, а деплой проверял сам себя, стоя в каталоге репозитория.
Вопрос "жив ли сервис" отвечает одинаково в обоих случаях - значит спрашивать
надо другое.
"""
import subprocess
import sys
from pathlib import Path

import pii_mask_enhanced


def test_where_prints_the_imported_module_path(tmp_path):
    out = subprocess.run([sys.executable, "-m", "pii_mask_enhanced.interfaces.cli", "where"],
                         capture_output=True, text=True, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert str(Path(pii_mask_enhanced.__file__).parent) in out.stdout, out.stdout
