import unittest

from scripts.wiki_fields import article_links, food_fields, wiki_recipe_text


class InfoboxTests(unittest.TestCase):
    def test_nested_markup_and_infobox_boundary(self):
        text = """{{Infobox food
        | country = [[United States|USA]]<ref>{{cite book|title=Example}}</ref>
        | region = {{ubl|North|South}}
        | main_ingredient = [[Banana]] and flour
        }} {{Unrelated|country=Other}}"""
        self.assertEqual(food_fields(text), ("USA", "North, South", None, None, "Banana and flour"))

    def test_redirect_and_commented_box(self):
        self.assertIsNone(food_fields("#REDIRECT [[Pancake]]"))
        self.assertIsNone(food_fields("<!-- {{Infobox food|country=X}} -->"))

    def test_preparation_is_read_from_prose(self):
        summary, preparation = wiki_recipe_text("""{{Infobox food|type=Soup}}
'''Herb soup''' is a traditional dish made with wild herbs.

== Preparation ==
Mix [[parsley]] with the stock and simmer over low heat.<ref>Source</ref>

== History ==
The soup was described in the local town records.""")
        self.assertEqual(summary, "Herb soup is a traditional dish made with wild herbs.")
        self.assertEqual(preparation, ["Mix parsley with the stock and simmer over low heat."])

    def test_list_links_exclude_references_and_file_links(self):
        self.assertEqual(article_links("* [[Herb soup#Preparation|Herb soup]] [[File:Soup.jpg]]\n"
                                       "== References ==\n[[Extra]]"),
                         {"Herb soup"})
