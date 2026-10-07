from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.align import Align

class CenteredConsole(Console):
    """A custom Console that automatically centers Panels and Tables."""
    def print(self, *objects, **kwargs):
        new_objects = []
        for obj in objects:
            if isinstance(obj, (Panel, Table)):
                obj.expand = False
                new_objects.append(Align.center(obj))
            else:
                new_objects.append(obj)
        super().print(*new_objects, **kwargs)

# Provide a globally accessible, centered console instance
console = CenteredConsole()
