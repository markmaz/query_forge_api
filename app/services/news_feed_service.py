import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag

from app.exceptions.service_error import ServiceError


def extract_image_url(style: str) -> Optional[str]:
    # Defensive regex to extract URL from background-image style
    match = re.search(r'url\((["\']?)(.*?)\1\)', style)
    
    if not match:
        return None

    url = match.group(2)

    # Basic validation: must be a valid URL and end with an image extension
    parsed = urlparse(url)
    if parsed.scheme in ('http', 'https') and parsed.netloc and parsed.path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        return url
    
    return None

logger = logging.getLogger(__name__)
URL = 'https://www.kytheralabs.com'

class NewsFeedService:
    def get_random_feed(self, number_of_articles: int) -> List[Dict[str, Any]]:
        response = requests.get(f"{URL}/resources")
        article_list = []

        # Check if the request was successful
        if response.status_code == 200:
            # Parse the page content
            soup = BeautifulSoup(response.text, 'html.parser')

            articles = soup.find_all('div', attrs={"role": "listitem"})  # Replace with the correct class
            for article in articles:
                link_tag = article.find('a', attrs={'class': ['toc-news-link-block', 'w-inline-block']}, href=True)
                link = link_tag['href']

                img = article.find('div', 'toc-image')
                image = None

                if img:
                    style = img.get("style")
                    image = extract_image_url(style)
                else:
                    img = article.find('div', 'toc-feature-image')
                    style = img.get("style")
                    image = extract_image_url(style)
                   

                
                title_block = article.find('div', 'toc-head-and-intro')
                title = next((el for el in title_block.contents if isinstance(el, Tag)), None).text
                description = title_block.find('p').text

                date_tag = article.find('div', 'blog-card-date').text
                article_list.append({'link': f"{URL}{link}", 'title': title, 'summary': description, 'date': date_tag, 'image': image})

            if number_of_articles > len(article_list):
                number_of_articles = len(article_list) - 1
            
            return article_list[:number_of_articles]
            #return random.sample(article_list, number_of_articles)
        else:
            logger.error(f"Problem getting articles - {response.text}")
            raise ServiceError("Problem getting artciles", response.status_code)