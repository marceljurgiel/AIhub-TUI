import logging

__version__ = "1.0.0"

# Library default: engine modules log to "aihub.*" and stay silent unless a
# front-end installs a handler (the bridge sends them to stderr, which the
# OpenTUI app appends to ~/.aihub/opentui-bridge.err.log).
logging.getLogger("aihub").addHandler(logging.NullHandler())
