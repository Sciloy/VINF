"""Let Scrapy recognize the same recipe even when its URL slug changes."""

from hashlib import sha256

from scrapy.utils.request import RequestFingerprinter

from food_crawler.spiders.food import recipe_url_details


class RecipeRequestFingerprinter(RequestFingerprinter):
    def fingerprint(self, request):
        recipe = recipe_url_details(request.url)
        if recipe is not None and request.method == "GET" and not request.meta.get("redirect_times"):
            # IDs identify individual Food.com entries, not families of dishes.
            return sha256(f"food.com/recipe/{recipe[1]}".encode()).digest()
        # Let canonical redirects complete even when they keep the recipe ID.
        return super().fingerprint(request)
