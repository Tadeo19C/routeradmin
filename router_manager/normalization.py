import re
import unicodedata
from typing import Dict, List, Optional, Tuple
from django.conf import settings
from django.core.exceptions import ValidationError


def strip_accents(text: str) -> str:
    if not text:
        return ''
    s = re.sub(r'[\u200b-\u200d\ufeff]', '', str(text))
    nfkd = unicodedata.normalize('NFKD', s)
    return ''.join(ch for ch in nfkd if not unicodedata.combining(ch))


def canonical_key(name: str) -> str:
    s = strip_accents(name or '').lower().strip()
    s = re.sub(r'[\-_\./\\]+', ' ', s)
    s = re.sub(r'[^\w\s]', ' ', s)
    s = re.sub(r'\b0+(\d+)\b', r'\1', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _singular_es_token(word: str) -> str:
    if len(word) > 4 and re.search(r'[dlnr]es$', word):
        return word[:-2]
    if len(word) > 3 and word.endswith('s') and not word.endswith('ss'):
        return word[:-1]
    return word


def category_match_key(name: str) -> str:
    """
    Normaliza nombres de Categoría ignorando mayúsculas, tildes y singular/plural:
    'Nodo' == 'Nodos', 'Cliente' == 'Clientes', 'Sucursal' == 'Sucursales'.
    """
    canon = canonical_key(name)
    if not canon:
        return ''
    return ' '.join(_singular_es_token(w) for w in canon.split())


def get_category_limit_message(attempted_name: str = '') -> str:
    max_cats = getattr(settings, 'MAX_DEVICE_CATEGORIES', 3)
    email = getattr(settings, 'CATEGORY_LIMIT_CONTACT_EMAIL', 'soporte@tdox-config.com')
    extra = f" ('{attempted_name}')" if attempted_name else ""
    return (
        f"No es posible crear más de {max_cats} categorías{extra}. "
        f"Para solicitar categorías adicionales por favor contáctese a: {email}"
    )


def ensure_default_category():
    from .models import DeviceCategory
    first = DeviceCategory.objects.order_by('position', 'id').first()
    if first:
        return first
    return DeviceCategory.objects.create(name='Nodos', position=1)


def match_category_from_candidates(raw_name: str, candidates: List):
    if not raw_name or not str(raw_name).strip():
        return None
    target_canon = canonical_key(raw_name)
    target_sing = category_match_key(raw_name)
    if not target_canon:
        return None

    for cat in candidates:
        if canonical_key(cat.name) == target_canon:
            return cat

    for cat in candidates:
        if category_match_key(cat.name) == target_sing:
            return cat

    return None


def find_matching_category(raw_name: str, queryset=None):
    from .models import DeviceCategory
    cats = list(queryset if queryset is not None else DeviceCategory.objects.all())
    return match_category_from_candidates(raw_name, cats)


def resolve_or_create_category(raw_name: str):
    from .models import DeviceCategory
    clean_display = re.sub(r'[\u200b-\u200d\ufeff]', '', str(raw_name or ''))
    clean_display = re.sub(r'\s+', ' ', clean_display).strip()
    if not clean_display:
        return ensure_default_category()

    existing = find_matching_category(clean_display)
    if existing:
        return existing

    max_cats = getattr(settings, 'MAX_DEVICE_CATEGORIES', 3)
    if DeviceCategory.objects.count() >= max_cats:
        raise ValidationError(get_category_limit_message(clean_display))

    next_pos = (DeviceCategory.objects.count() or 0) + 1
    return DeviceCategory.objects.create(name=clean_display, position=next_pos)


_NODE_PREFIXES = (
    'nodo ', 'node ', 'grupo ', 'group ', 'sitio ', 'pop ', 'zona ',
    'del ', 'de ', 'el ', 'la ', 'los ', 'las ',
)
_NODE_SUFFIXES = (' nodo', ' node', ' grupo', ' group')


def core_node_key(name: str) -> str:
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
    tokens = [t for t in core_key.split() if t not in ('de', 'del', 'el', 'la', 'los', 'las', 'nodo', 'node', 'grupo')]
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


def find_matching_node(raw_name: str, category=None, queryset=None):
    from .models import RouterGroup

    if queryset is not None:
        groups = list(queryset)
    elif category is not None:
        groups = list(RouterGroup.objects.filter(category=category))
    else:
        groups = list(RouterGroup.objects.all())
    return match_node_from_candidates(raw_name, groups)


class _VirtualCategory:
    def __init__(self, name: str):
        self.name = name
        self.id = None


class _VirtualNode:
    def __init__(self, name: str):
        self.name = name.upper()
        self.default_group = False
        self.id = 999999999


class BatchCategoryGroupResolver:
    """
    Resuelve pares (Categoría, Grupo) durante la lectura de Excel sin crear huérfanos
    en la vista previa, respetando estrictamente el máximo de 3 categorías.
    """
    def __init__(self):
        from .models import DeviceCategory, RouterGroup
        self.max_cats = getattr(settings, 'MAX_DEVICE_CATEGORIES', 3)
        db_cats = list(DeviceCategory.objects.order_by('position', 'id'))
        if not db_cats:
            db_cats = [ensure_default_category()]
        self.default_category_name = db_cats[0].name
        self.cat_candidates = list(db_cats)

        self.groups_by_cat_key: Dict[str, List] = {}
        for c in db_cats:
            ck = category_match_key(c.name)
            self.groups_by_cat_key[ck] = list(RouterGroup.objects.filter(category=c))

    def resolve(self, raw_category: str, raw_group: str, line_number: int = 0) -> Tuple[str, str]:
        clean_cat = re.sub(r'[\u200b-\u200d\ufeff]', '', str(raw_category or ''))
        clean_cat = re.sub(r'\s+', ' ', clean_cat).strip()
        if not clean_cat:
            clean_cat = self.default_category_name

        matched_cat = match_category_from_candidates(clean_cat, self.cat_candidates)
        if matched_cat:
            resolved_cat_name = matched_cat.name
        else:
            if len(self.cat_candidates) >= self.max_cats:
                existing_names = ', '.join(c.name for c in self.cat_candidates)
                prefix = f"Fila {line_number}: " if line_number else ""
                raise ValidationError(
                    f"{prefix}{get_category_limit_message(clean_cat)} "
                    f"(Categorías actuales: {existing_names})."
                )
            vcat = _VirtualCategory(clean_cat)
            self.cat_candidates.append(vcat)
            resolved_cat_name = clean_cat

        ck = category_match_key(resolved_cat_name)
        grp_candidates = self.groups_by_cat_key.setdefault(ck, [])

        clean_grp = re.sub(r'[\u200b-\u200d\ufeff]', '', str(raw_group or ''))
        clean_grp = re.sub(r'\s+', ' ', clean_grp).strip().upper()
        if not clean_grp:
            default_g = next((g for g in grp_candidates if getattr(g, 'default_group', False)), None)
            clean_grp = default_g.name.upper() if default_g else 'GENERAL'

        matched_grp = match_node_from_candidates(clean_grp, grp_candidates)
        if matched_grp:
            resolved_grp_name = matched_grp.name.upper()
        else:
            vgrp = _VirtualNode(clean_grp)
            grp_candidates.append(vgrp)
            resolved_grp_name = clean_grp

        return resolved_cat_name, resolved_grp_name


class BatchNodeResolver(BatchCategoryGroupResolver):
    """Compatibilidad hacia atrás con llamadas simples de 1 argumento."""
    def resolve_name(self, raw_name: str) -> str:
        _, grp_name = self.resolve('', raw_name)
        return grp_name


def resolve_or_create_node(raw_name: str, category=None):
    from .models import RouterGroup

    if category is None:
        category = ensure_default_category()

    clean_display = re.sub(r'[\u200b-\u200d\ufeff]', '', str(raw_name or ''))
    clean_display = re.sub(r'\s+', ' ', clean_display).strip().upper()
    if not clean_display:
        default_node = RouterGroup.objects.filter(category=category, default_group=True).first()
        if default_node:
            return default_node
        clean_display = 'GENERAL'

    existing = find_matching_node(clean_display, category=category)
    if existing:
        if existing.name != existing.name.upper():
            existing.name = existing.name.upper()
            existing.save(update_fields=['name'])
        return existing

    return RouterGroup.objects.create(category=category, name=clean_display)


def find_matching_client(raw_name: str, exclude_pk: Optional[int] = None):
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
