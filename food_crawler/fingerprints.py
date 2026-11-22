"""Rozpoznávanie duplicitných URL podľa ID receptu."""

from hashlib import sha256

from scrapy.utils.request import RequestFingerprinter

from food_crawler.spiders.food import recipe_url_details


class RecipeRequestFingerprinter(RequestFingerprinter):
    def fingerprint(self, request):
        recipe = recipe_url_details(request.url)
        if (
            recipe is not None
            and request.method == "GET"
            and not request.meta.get("redirect_times")
        ):
            # ID identifikuje konkrétny recept.
            return sha256(f"food.com/recipe/{recipe[1]}".encode()).digest()
        # Presmerovanie musí dobehnúť aj pri rovnakom ID.
        return super().fingerprint(request)
