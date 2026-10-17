class FakeItem:
    def __init__(self, kind, name):
        self.kind = kind
        self.name = name


def discover(_dirs):
    return [
        FakeItem(kind, name)
        for (kind, name) in {("skills", "test-skill"), ("agents", "test-agent")}
    ]


def state_key(kind, name):
    return f"{kind}/{name}"
