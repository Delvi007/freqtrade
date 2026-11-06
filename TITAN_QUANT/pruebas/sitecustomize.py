import os
if os.environ.get("TITAN_FIXTURES"):
    import fixtures_red
    fixtures_red.install()
