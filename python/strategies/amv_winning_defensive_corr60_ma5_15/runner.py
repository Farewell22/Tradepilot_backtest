"""Full-position MA5 weak entries with a minimum daily AMV return."""
from pathlib import Path
import yaml
from python.strategies.amv_winning_defensive_corr60_ma5.runner import run as run_comparison


def run(request):
    settings = yaml.safe_load(request.config_path.read_text())
    minimum = float(settings['weak_entry']['minimum_day_return'])
    return run_comparison(request, minimum_weak_return=minimum,
                          extra_code_sources=(Path(__file__),))
