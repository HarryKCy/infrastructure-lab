"""Optional machine-readable recap for the idempotency runner."""
import json
import os
import tempfile
from pathlib import Path
from ansible.plugins.callback import CallbackBase


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'lab_stats'
    CALLBACK_NEEDS_ENABLED = True

    def v2_playbook_on_stats(self, stats):
        destination = os.environ.get('LAB_STATS_FILE')
        if destination:
            target = Path(destination)
            fd, temporary = tempfile.mkstemp(prefix=target.name + '.', dir=target.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump({host: stats.summarize(host) for host in stats.processed}, stream)
                    stream.write('\n')
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
