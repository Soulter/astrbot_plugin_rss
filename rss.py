from dataclasses import dataclass

@dataclass
class RSSItem:
    chan_title: str
    title: str
    link: str
    description: str
    pubDate: str
    pubDate_timestamp: int

    def __str__(self):
        return f"{self.title} - {self.link} - {self.description} - {self.pubDate}"