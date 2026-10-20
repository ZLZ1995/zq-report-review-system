"""Server adapters require an injected credential; never read desktop credentials."""


def load_key():
    return None


def data_home():
    raise RuntimeError('Server data results must be returned to the authenticated caller')
