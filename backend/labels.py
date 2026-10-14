"""Display names; model class IDs and stored count keys remain unchanged."""
LABELS = {"Pin": "Клапан", "Piston": "Поршень", "Shatun": "Шатун"}


def display_name(name):
    return LABELS.get(name, name)
