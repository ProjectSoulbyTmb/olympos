class Node:
    def __init__(self, name, update_fn=None):
        self.name = name
        self.update_fn = update_fn
        self.children = []
        self.parent = None

    def add(self, node):
        node.parent = self
        self.children.append(node)
        return node

    def find(self, name):
        if self.name == name:
            return self
        for child in self.children:
            found = child.find(name)
            if found is not None:
                return found
        return None

    def path(self):
        names = []
        node = self
        while node is not None:
            names.append(node.name)
            node = node.parent
        return "/".join(reversed(names))

    def update(self, dt):
        if self.update_fn is not None:
            self.update_fn(dt)
        for child in list(self.children):
            child.update(dt)


class Scene:
    def __init__(self, root_name="root"):
        self.root = Node(root_name)
        self.order_log = []

    def add(self, parent_name, node):
        parent = self.root.find(parent_name)
        if parent is None:
            raise KeyError(f"no node named {parent_name!r}")
        return parent.add(node)

    def update(self, dt):
        self.root.update(dt)
