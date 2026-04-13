import traceback
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader('src/landppt/web/templates'))
try:
    env.get_template('pages/account/profile.html')
    print('OK')
except BaseException:
    traceback.print_exc()

