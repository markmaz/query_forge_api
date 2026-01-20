from flask_restx import Namespace, Resource

from app.decorators.security import token_required
from app.services.news_feed_service import NewsFeedService

news_ns = Namespace("news", description="Blog articles from Kythera")

@news_ns.route("/<int:number_of_articles>")
class GetRandomNews(Resource):

    @token_required
    def get(self, number_of_articles: int):
        news = NewsFeedService()
        return news.get_random_feed(number_of_articles)