"""MKTT Macro section — Liquidity Dashboard + Sector RRG."""
from flask import Blueprint

macro_bp = Blueprint('macro', __name__,
                     template_folder='../templates',
                     url_prefix='/macro')

from . import routes  # noqa: E402, F401
