from flask import Blueprint

main = Blueprint("main", __name__)
from . import views, general, masri_views
