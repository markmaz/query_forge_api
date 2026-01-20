from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.news_feed_service import NewsFeedService, extract_image_url


class _Resp:
    def __init__(self, status_code: int, text: str = "", payload=None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_extract_image_url() -> None:
    style = "background-image:url('https://example.com/a.jpg')"
    assert extract_image_url(style) == "https://example.com/a.jpg"
    assert extract_image_url("background-image:url('/nope.png')") is None
    assert extract_image_url("nope") is None


def test_get_random_feed_success(monkeypatch: pytest.MonkeyPatch) -> None:
    html = """
    <div role="listitem">
      <a class="toc-news-link-block w-inline-block" href="/post1"></a>
      <div class="toc-image" style="background-image:url('https://example.com/a.jpg')"></div>
      <div class="toc-head-and-intro"><div>Title One</div><p>Desc One</p></div>
      <div class="blog-card-date">2024-01-01</div>
    </div>
    <div role="listitem">
      <a class="toc-news-link-block w-inline-block" href="/post2"></a>
      <div class="toc-feature-image" style="background-image:url('https://example.com/b.jpg')"></div>
      <div class="toc-head-and-intro"><div>Title Two</div><p>Desc Two</p></div>
      <div class="blog-card-date">2024-01-02</div>
    </div>
    """

    monkeypatch.setattr("app.services.news_feed_service.requests.get", lambda *_args, **_kwargs: _Resp(200, text=html))
    svc = NewsFeedService()
    items = svc.get_random_feed(5)

    assert len(items) == 1  # count limited to len-1 when over-requested
    assert items[0]["title"] == "Title One"
    assert items[0]["image"] == "https://example.com/a.jpg"


def test_get_random_feed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.news_feed_service.requests.get", lambda *_args, **_kwargs: _Resp(500, text="boom"))
    svc = NewsFeedService()
    with pytest.raises(ServiceError):
        svc.get_random_feed(1)
