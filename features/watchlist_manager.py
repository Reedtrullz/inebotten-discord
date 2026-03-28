#!/usr/bin/env python3
"""
Watchlist Manager for Inebotten
Manages movie and series recommendations from Discord channels
"""

import json
import random
from datetime import datetime
from pathlib import Path


class WatchlistManager:
    """
    Manages watchlists for movies and series
    Can import from Discord channels or store locally
    """
    
    def __init__(self, storage_path=None):
        if storage_path is None:
            storage_path = Path.home() / '.hermes' / 'discord' / 'watchlist.json'
        
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.watchlist = self._load_watchlist()
        
        # Default starter recommendations if no watchlist exists
        self.default_movies = [
            {"title": "Inception", "type": "movie", "genre": "Sci-Fi", "year": 2010},
            {"title": "The Grand Budapest Hotel", "type": "movie", "genre": "Comedy", "year": 2014},
            {"title": "Parasitt", "type": "movie", "genre": "Thriller", "year": 2019},
            {"title": "Interstellar", "type": "movie", "genre": "Sci-Fi", "year": 2014},
            {"title": "The Dark Knight", "type": "movie", "genre": "Action", "year": 2008},
        ]
        
        self.default_series = [
            {"title": "The Office (US)", "type": "series", "genre": "Comedy", "episodes": "9 sesonger"},
            {"title": "Breaking Bad", "type": "series", "genre": "Drama", "episodes": "5 sesonger"},
            {"title": "Dark", "type": "series", "genre": "Sci-Fi/Thriller", "episodes": "3 sesonger"},
            {"title": "Brooklyn Nine-Nine", "type": "series", "genre": "Comedy", "episodes": "8 sesonger"},
            {"title": "Stranger Things", "type": "series", "genre": "Sci-Fi/Horror", "episodes": "4 sesonger"},
        ]
    
    def _load_watchlist(self):
        """Load watchlist from storage"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {'movies': [], 'series': []}
    
    def _save_watchlist(self):
        """Save watchlist to storage"""
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(self.watchlist, f, ensure_ascii=False, indent=2)
    
    def add_from_discord_message(self, title, content_type='movie', **kwargs):
        """
        Add a movie/series from a Discord message
        
        Args:
            title: Movie/series title
            content_type: 'movie' or 'series'
            **kwargs: Extra info like genre, year, platform, etc.
        """
        item = {
            'title': title,
            'type': content_type,
            'added_at': datetime.now().isoformat(),
            'watched': False,
            **kwargs
        }
        
        if content_type == 'movie':
            self.watchlist['movies'].append(item)
        else:
            self.watchlist['series'].append(item)
        
        self._save_watchlist()
        return True
    
    def get_random_suggestion(self, content_type=None, genre=None):
        """
        Get a random suggestion
        
        Args:
            content_type: 'movie', 'series', or None for both
            genre: Optional genre filter
        """
        candidates = []
        
        # Add from watchlist
        if content_type in (None, 'movie'):
            candidates.extend([m for m in self.watchlist['movies'] if not m.get('watched', False)])
        if content_type in (None, 'series'):
            candidates.extend([s for s in self.watchlist['series'] if not s.get('watched', False)])
        
        # Add defaults if watchlist is empty
        if not candidates:
            if content_type == 'movie' or content_type is None:
                candidates.extend(self.default_movies)
            if content_type == 'series' or content_type is None:
                candidates.extend(self.default_series)
        
        # Filter by genre if specified
        if genre:
            candidates = [c for c in candidates if genre.lower() in c.get('genre', '').lower()]
        
        if not candidates:
            return None
        
        return random.choice(candidates)
    
    def get_watchlist_summary(self):
        """Get summary of watchlist"""
        unwatched_movies = [m for m in self.watchlist['movies'] if not m.get('watched', False)]
        unwatched_series = [s for s in self.watchlist['series'] if not s.get('watched', False)]
        
        return {
            'movies_total': len(self.watchlist['movies']),
            'movies_unwatched': len(unwatched_movies),
            'series_total': len(self.watchlist['series']),
            'series_unwatched': len(unwatched_series),
        }
    
    def mark_as_watched(self, title):
        """Mark an item as watched"""
        for item in self.watchlist['movies'] + self.watchlist['series']:
            if item['title'].lower() == title.lower():
                item['watched'] = True
                item['watched_at'] = datetime.now().isoformat()
                self._save_watchlist()
                return True
        return False
    
    def format_suggestion(self, item, lang='no'):
        """Format a suggestion for display in specified language"""
        title = item['title']
        
        if lang == 'no':
            content_type_label = "🎬 Film" if item.get('type') == 'movie' else "📺 Serie"
            header = "🎬 **Kveldens forslag!**"
            genre_label = "Sjanger"
            year_label = "År"
            length_label = "Lengde"
        else:
            content_type_label = "🎬 Movie" if item.get('type') == 'movie' else "📺 Series"
            header = "🎬 **Tonight's Suggestion!**"
            genre_label = "Genre"
            year_label = "Year"
            length_label = "Length"
        
        genre = item.get('genre', '')
        
        lines = [
            header,
            "",
            f"**{title}**",
            f"{content_type_label}",
        ]
        
        if genre:
            lines.append(f"{genre_label}: {genre}")
        
        if item.get('type') == 'movie' and item.get('year'):
            lines.append(f"{year_label}: {item['year']}")
        elif item.get('type') == 'series' and item.get('episodes'):
            lines.append(f"{length_label}: {item['episodes']}")
        
        # Add a fun comment based on genre and language
        comments_no = {
            'comedy': ['Perfekt for en god latter! 😂', 'Koselig kveld i vente! 🍿'],
            'drama': ['Dramatisk og engasjerende! 🎭', 'For de som vil gråte litt 😢'],
            'sci-fi': ['Tankevekkende! 🚀', 'For de som liker å drømme stort 🌌'],
            'thriller': ['Spenning til max! 😰', 'Hjertet i halsen-garanti! 💓'],
            'horror': ['Ikke for pyser! 👻', 'Lys på, dyner over hodet! 🛏️'],
            'action': ['Adrenalinfylt! 💥', 'For de som liker fart og spenning! 🏎️'],
        }
        comments_en = {
            'comedy': ['Perfect for a good laugh! 😂', 'Cozy evening ahead! 🍿'],
            'drama': ['Dramatic and engaging! 🎭', 'For those who want to cry a bit 😢'],
            'sci-fi': ['Thought-provoking! 🚀', 'For dreamers 🌌'],
            'thriller': ['Maximum suspense! 😰', 'Heart-in-throat guarantee! 💓'],
            'horror': ['Not for the faint-hearted! 👻', 'Lights on, covers over head! 🛏️'],
            'action': ['Adrenaline-filled! 💥', 'For speed and thrill lovers! 🏎️'],
        }
        
        comments = comments_no if lang == 'no' else comments_en
        
        if genre:
            genre_lower = genre.lower()
            for key, comments_list in comments.items():
                if key in genre_lower:
                    lines.append(f"\n💬 {random.choice(comments_list)}")
                    break
        
        return "\n".join(lines)
    
    def format_watchlist_status(self, lang='no'):
        """Format watchlist status in specified language"""
        summary = self.get_watchlist_summary()
        
        if lang == 'no':
            header = "📋 **Watchlist Status**"
            movies_label = "Filmer"
            series_label = "Serier"
            unwatched_label = "usette"
            total_label = "totalt"
            empty_msg = "\n🎉 Watchlista er tom! Tid for å legge til mer?"
            low_msg = "\n⚠️ Det begynner å bli tomt i lista..."
            waiting_msg = "\n✨ {count} titler venter på deg!"
        else:
            header = "📋 **Watchlist Status**"
            movies_label = "Movies"
            series_label = "Series"
            unwatched_label = "unwatched"
            total_label = "total"
            empty_msg = "\n🎉 Watchlist is empty! Time to add more?"
            low_msg = "\n⚠️ Getting low on the list..."
            waiting_msg = "\n✨ {count} titles waiting for you!"
        
        lines = [
            header,
            "",
            f"🎬 {movies_label}: {summary['movies_unwatched']} {unwatched_label} ({summary['movies_total']} {total_label})",
            f"📺 {series_label}: {summary['series_unwatched']} {unwatched_label} ({summary['series_total']} {total_label})",
        ]
        
        total_unwatched = summary['movies_unwatched'] + summary['series_unwatched']
        
        if total_unwatched == 0:
            lines.append(empty_msg)
        elif total_unwatched < 5:
            lines.append(low_msg)
        else:
            lines.append(waiting_msg.format(count=total_unwatched))
        
        return "\n".join(lines)


def parse_watchlist_command(message_content):
    """
    Parse watchlist commands (Norwegian and English)
    
    Returns:
        dict with action and data, or None
    """
    content_lower = message_content.lower()
    
    # Detect language
    lang = 'no' if any(word in content_lower for word in ['filmforslag', 'serieforslag', 'anbefaling', 'hva skal vi se']) else 'en'
    
    # Check for suggestion request
    suggestion_keywords = [
        'hva skal vi se', 'filmforslag', 'serieforslag', 'anbefaling',
        'movie suggestion', 'series suggestion', 'what should we watch', 'recommend'
    ]
    
    for keyword in suggestion_keywords:
        if keyword in content_lower:
            # Determine type
            content_type = None
            if any(word in content_lower for word in ['film', 'movie', 'filmforslag']):
                content_type = 'movie'
            elif any(word in content_lower for word in ['serie', 'series', 'serieforslag', 'tv show']):
                content_type = 'series'
            
            # Check for genre
            genre = None
            genres = ['komedie', 'comedy', 'drama', 'sci-fi', 'action', 'thriller', 'horror']
            for g in genres:
                if g in content_lower:
                    genre = g
                    break
            
            return {'action': 'suggest', 'type': content_type, 'genre': genre, 'lang': lang}
    
    # Check for watchlist status
    if any(word in content_lower for word in ['watchlist', 'watchlista', 'hva har vi']):
        return {'action': 'status', 'lang': lang}
    
    # Check for adding item
    if any(phrase in content_lower for phrase in ['legg til', 'add to watchlist', 'husk å se']):
        return {'action': 'add', 'lang': lang}
    
    return None


# Quick test
if __name__ == "__main__":
    print("=== Watchlist Manager Test ===\n")
    
    manager = WatchlistManager(storage_path='/tmp/test_watchlist.json')
    
    # Test suggestion
    suggestion = manager.get_random_suggestion()
    if suggestion:
        print("Random suggestion:")
        print(manager.format_suggestion(suggestion))
        print()
    
    # Test status
    print(manager.format_watchlist_status())
    
    # Cleanup
    if manager.storage_path.exists():
        manager.storage_path.unlink()
