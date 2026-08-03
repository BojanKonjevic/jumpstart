"""Explicit separation of template and addon just_recipes."""

from __future__ import annotations

from dataclasses import dataclass, field

from zenit.core.constants import extract_recipe_name as _recipe_name


@dataclass
class RecipeCollection:
    """Holds template and addon just_recipes separately.

    ``template`` recipes always win when an addon recipe shares the same name
    during deduplication.  Operates on raw (unrendered) recipes - recipe
    names are determined by text before ``:``, which Jinja2 rendering
    cannot change.
    """

    template: list[str] = field(default_factory=list)
    addon: list[str] = field(default_factory=list)

    def resolve(self) -> list[str]:
        """Return deduplicated list: template recipes first, then unique addon recipes.

        An addon recipe is dropped if its name matches a template recipe.
        """
        template_names = {
            n
            for r in self.template
            if r.strip()
            for n in (_recipe_name(r),)
            if n is not None
        }
        unique_addon = [
            r for r in self.addon if r.strip() and _recipe_name(r) not in template_names
        ]
        return list(self.template) + unique_addon
