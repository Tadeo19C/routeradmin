import re
import unicodedata
from typing import List, Optional


def strip_accents(text: str) -> str:
    if not text:
        return ''
    s = re.sub(r'[\u200b-\u200d\ufeff]', '', str(text))
    nfkd = unicodedata.normalize('NFKD', s)
    return ''.join(ch for ch in nfkd if not unicodedata.combining(ch))


def canonical_key(name: str) -> str:
    """
    Normaliza un nombre ignorando mayúsculas/minúsculas, tildes/acentos/ñ,
    guiones, guiones bajos, puntos, paréntesis y espacios múltiples.
    Ej: '  Nódo_Centro - 01 ' -> 'nodo centro 1'
    """
    s = strip_accents(name or '').lower().strip()
    s = re.sub(r'[\-_\./\\]+', ' ', s)
    s = re.sub(r'[^\w\s]', ' ', s)
    s = re.sub(r'\b0+(\d+)\b', r'\1', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


_NODE_PREFIXES = (
    'nodo ', 'node ', 'sitio ', 'pop ', 'zona ',
    'del ', 'de ', 'el ', 'la ', 'los ', 'las ',
)
_NODE_SUFFIXES = (' nodo', ' node')


def core_node_key(name: str) -> str:
    """
    Clave semántica para Nodos que unifica variantes y combinaciones comunes:
    'Crucero', 'El Crucero', 'Nodo Crucero', 'Nodo del Crucero', 'nodo-crucero',
    'Crucero Nodo', 'CRUCERO' -> 'crucero'
    """
    key = canonical_key(name)
    if not key:
        return ''

    changed = True
    while changed:
        changed = False
        for prefix in _NODE_PREFIXES:
            if key.startswith(prefix) and len(key) > len(prefix):
                key = key[len(prefix):].strip()
                changed = True
        for suffix in _NODE_SUFFIXES:
            if key.endswith(suffix) and len(key) > len(suffix):
                key = key[:-len(suffix)].strip()
                changed = True
    return key


def _sorted_tokens_key(core_key: str) -> Optional[str]:
    if not core_key:
        return None
    tokens = [t for t in core_key.split() if t not in ('de', 'del', 'el', 'la', 'los', 'las', 'nodo', 'node')]
    if len(tokens) < 2:
        return None
    num_count = sum(1 for t in tokens if t.isdigit())
    if num_count > 1:
        return None
    return ' '.join(sorted(tokens))


def match_node_from_candidates(raw_name: str, candidates: List):
    if not raw_name or not str(raw_name).strip():
        return None

    target_canon = canonical_key(raw_name)
    target_core = core_node_key(raw_name)
    if not target_canon:
        return None

    for grp in candidates:
        if canonical_key(grp.name) == target_canon:
            return grp

    if target_core:
        core_matches = [grp for grp in candidates if core_node_key(grp.name) == target_core]
        if len(core_matches) == 1:
            return core_matches[0]
        elif len(core_matches) > 1:
            core_matches.sort(key=lambda g: (not getattr(g, 'default_group', False), getattr(g, 'id', 0) or 0))
            return core_matches[0]

    target_sorted = _sorted_tokens_key(target_core)
    if target_sorted:
        token_matches = [
            grp for grp in candidates
            if _sorted_tokens_key(core_node_key(grp.name)) == target_sorted
        ]
        if len(token_matches) == 1:
            return token_matches[0]
        elif len(token_matches) > 1:
            token_matches.sort(key=lambda g: (not getattr(g, 'default_group', False), getattr(g, 'id', 0) or 0))
            return token_matches[0]

    return None


def find_matching_node(raw_name: str, queryset=None):
    from .models import RouterGroup

    groups = list(queryset if queryset is not None else RouterGroup.objects.all())
    return match_node_from_candidates(raw_name, groups)


class _VirtualNode:
    def __init__(self, name: str):
        self.name = name.upper()
        self.default_group = False
        self.id = 999999999


class BatchNodeResolver:
    """
    Resuelve nombres de Nodos para importación masiva en MAYÚSCULAS:
    unifica contra los Nodos ya existentes en BD y contra los Nodos nuevos
    que aparezcan en filas anteriores del mismo archivo Excel.
    """
    def __init__(self):
        from .models import RouterGroup
        self.db_nodes = list(RouterGroup.objects.all())
        default_node = next((g for g in self.db_nodes if g.default_group), None)
        self.default_name = default_node.name.upper() if default_node else 'GENERAL'
        self.candidates = list(self.db_nodes)

    def resolve_name(self, raw_name: str) -> str:
        clean_display = re.sub(r'[\u200b-\u200d\ufeff]', '', str(raw_name or ''))
        clean_display = re.sub(r'\s+', ' ', clean_display).strip().upper()
        if not clean_display:
            clean_display = self.default_name

        matched = match_node_from_candidates(clean_display, self.candidates)
        if matched:
            return matched.name.upper()

        virtual = _VirtualNode(clean_display)
        self.candidates.append(virtual)
        return clean_display


def resolve_or_create_node(raw_name: str):
    """
    Devuelve el RouterGroup existente si coincide en cualquier variante/combinación,
    o crea uno nuevo registrado estrictamente en MAYÚSCULAS.
    """
    from .models import RouterGroup

    clean_display = re.sub(r'[\u200b-\u200d\ufeff]', '', str(raw_name or ''))
    clean_display = re.sub(r'\s+', ' ', clean_display).strip().upper()
    if not clean_display:
        default_node = RouterGroup.objects.filter(default_group=True).first()
        if default_node:
            return default_node
        clean_display = 'GENERAL'

    existing = find_matching_node(clean_display)
    if existing:
        if existing.name != existing.name.upper():
            existing.name = existing.name.upper()
            existing.save(update_fields=['name'])
        return existing

    return RouterGroup.objects.create(name=clean_display)


def find_matching_client(raw_name: str, exclude_pk: Optional[int] = None):
    """
    Busca un RouterClient existente ignorando mayúsculas, tildes, guiones y espacios extra.
    """
    from .models import RouterClient

    target_canon = canonical_key(raw_name)
    if not target_canon:
        return None

    qs = RouterClient.objects.all()
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)

    for cl in qs:
        if canonical_key(cl.name) == target_canon:
            return cl
    return None
