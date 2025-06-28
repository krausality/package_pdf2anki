# genanki Features Documentation for Developers

This document contains research findings about genanki library capabilities and potential features for the pdf2anki project.

## Research Methods & Findings

### Method 1: Constructor Signature Analysis
**Command Used:**
```bash
python -c "import genanki; import inspect; print(inspect.signature(genanki.Note.__init__))"
```

**Result:**
```
(self, model=None, fields=None, sort_field=None, tags=None, guid=None, due=0)
```

**Finding:** genanki Note constructor accepts 6 parameters beyond `self`, revealing all available optional fields.

### Method 2: Source Code Inspection
**Command Used:**
```bash
python -c "import genanki; import inspect; print(inspect.getsource(genanki.Note.__init__))"
```

**Result:**
```python
def __init__(self, model=None, fields=None, sort_field=None, tags=None, guid=None, due=0):
    self.model = model
    self.fields = fields
    self.sort_field = sort_field
    self.tags = tags or []
    self.due = due
    try:
        self.guid = guid
    except AttributeError:
        # guid was defined as a property
        pass
```

**Finding:** Confirms parameter handling and shows that `tags` defaults to empty list if None.

### Method 3: Class Attributes Discovery
**Command Used:**
```bash
python -c "import genanki; print(genanki.Note.__dict__.keys())"
```

**Result:**
```
dict_keys(['__module__', '__firstlineno__', '_INVALID_HTML_TAG_RE', '__init__', 'sort_field', 'tags', 'cards', '_cloze_cards', '_front_back_cards', 'guid', '_check_number_model_fields_matches_num_fields', '_find_invalid_html_tags_in_field', '_check_invalid_html_tags_in_fields', 'write_to_db', '_format_fields', '_format_tags', '__repr__', '__static_attributes__', '__dict__', '__weakref__', '__doc__'])
```

**Finding:** Reveals additional methods like `_cloze_cards`, `_front_back_cards`, indicating support for different card types.

### Method 4: Instance Attributes Analysis
**Command Used:**
```bash
python -c "import genanki; note = genanki.Note(); print([attr for attr in dir(note) if not attr.startswith('_')])"
```

**Result:**
```
['cards', 'due', 'fields', 'guid', 'model', 'sort_field', 'tags', 'write_to_db']
```

**Finding:** Confirms public attributes available on Note instances.

### Method 5: Official Documentation Review
**Sources Examined:**
- https://github.com/kerrickstaley/genanki (README.md)
- https://pypi.org/project/genanki/ 
- https://docs.ankiweb.net/studying.html
- https://docs.ankiweb.net/getting-started.html

**Key Findings from Documentation:**

#### genanki README - Note GUIDs Section
```
`Note`s have a `guid` property that uniquely identifies the note. If you import a new note that has 
the same GUID as an existing note, the new note will overwrite the old one (as long as their models 
have the same fields).
```

#### genanki README - sort_field Section  
```
Anki has a value for each `Note` called the `sort_field`. Anki uses this value to sort the cards in 
the Browse interface. By default, the `sort_field` is the first field, but you can change it by 
passing `sort_field=` to `Note()`.
```

#### genanki README - Media Files Section
```
To add sounds or images, set the `media_files` attribute on your `Package`:
my_package = genanki.Package(my_deck)
my_package.media_files = ['sound.mp3', 'images/image.jpg']
```

#### Anki Documentation - Due Dates
From https://docs.ankiweb.net/studying.html:
```
Set Due Date: Puts cards in the review queue, and makes them due on a certain date.
```

## Available Optional Fields Summary

### Currently Implemented
- ✅ **`tags`** - List of strings for categorizing cards

### Available for Implementation

#### 1. `sort_field` (High Priority)
- **Purpose:** Controls card sorting in Anki Browse interface
- **Type:** String
- **Default:** First field (front) if not specified
- **JSON Example:**
  ```json
  {
    "front": "Advanced Topic",
    "back": "Complex explanation", 
    "sort_field": "01_Advanced"
  }
  ```

#### 2. `guid` (High Priority)
- **Purpose:** Prevents duplicates, enables card updates
- **Type:** String (should be unique)
- **Default:** Hash of field values if not specified
- **JSON Example:**
  ```json
  {
    "front": "What is photosynthesis?",
    "back": "Process converting light to energy",
    "guid": "biology-photosynthesis-001"
  }
  ```

#### 3. `due` (Medium Priority)
- **Purpose:** Schedule card's first appearance (days from today)
- **Type:** Integer (days)
- **Default:** 0 (available immediately)
- **JSON Example:**
  ```json
  {
    "front": "Advanced topic for later",
    "back": "Study this in a week",
    "due": 7
  }
  ```

### Advanced Features (Lower Priority)

#### 4. Custom Models
- **Current:** Hardcoded to `genanki.BASIC_MODEL`
- **Potential:** Support for cloze deletion, custom styling
- **Implementation:** Would require model definition in JSON

#### 5. Media Files
- **Purpose:** Add images, audio to cards
- **Implementation:** Would require file handling, Package.media_files

## Implementation Priority Recommendations

### Phase 1 (High Impact, Low Complexity)
1. **`guid`** - Critical for deck regeneration without duplicates
2. **`sort_field`** - Simple to implement, improves organization

### Phase 2 (Medium Impact, Medium Complexity) 
3. **`due`** - Useful for spaced content introduction

### Phase 3 (High Impact, High Complexity)
4. **Custom models** - Enables advanced card types
5. **Media support** - Enables multimedia cards

## Code Implementation Notes

### Current Implementation Pattern
```python
note = genanki.Note(
    model=genanki.BASIC_MODEL,
    fields=[card['front'], card['back']],
    tags=card_tags  # ✅ Already implemented
)
```

### Extended Implementation Pattern
```python
note = genanki.Note(
    model=genanki.BASIC_MODEL,
    fields=[card['front'], card['back']],
    tags=card.get('tags', []),
    sort_field=card.get('sort_field'),  # 🔄 Could implement
    guid=card.get('guid'),              # 🔄 Could implement  
    due=card.get('due', 0)              # 🔄 Could implement
)
```

## Research Validation

All findings were validated through:
1. ✅ Direct code inspection of genanki library
2. ✅ Official documentation review
3. ✅ Constructor signature analysis
4. ✅ Runtime attribute inspection
5. ✅ Anki official documentation cross-reference

## Files Modified During Research
- `pdf2anki/text2anki.py` - Added tags support
- `test_cards_with_tags.json` - Created test file with tags
- Various test .apkg files generated for validation

---

Based on my research of the genanki library and Anki documentation, here are the **other optional fields** that could be implemented for flashcard creation:

## **Available genanki Note Constructor Parameters**

From the genanki Note constructor signature: `__init__(self, model=None, fields=None, sort_field=None, tags=None, guid=None, due=0)`

### **1. `sort_field` Parameter**
**What it is:** Controls how cards are sorted in Anki's Browse interface
**Source:** Found in genanki README documentation and constructor signature
**Use case:** 
- Useful for organizing cards alphabetically or by importance
- By default, Anki uses the first field (front) for sorting
- Could allow custom sorting like by difficulty, topic, or creation date

**JSON Example:**
```json
{
  "front": "Advanced Calculus Concept",
  "back": "Integration by parts formula",
  "tags": ["calculus", "advanced"],
  "sort_field": "01_Advanced"
}
```

### **2. `guid` Parameter** 
**What it is:** Globally Unique Identifier for the note
**Source:** Extensively documented in genanki README under "Note GUIDs" section
**Use case:**
- Prevents duplicate imports when re-generating decks
- Allows updating existing cards without creating duplicates
- Enables stable card identity across deck regenerations

**JSON Example:**
```json
{
  "front": "What is photosynthesis?",
  "back": "Process plants use to convert light to energy",
  "guid": "biology-photosynthesis-001"
}
```

### **3. `due` Parameter**
**What it is:** Sets when a card should first appear for review (in days from today)
**Source:** Found in constructor signature, relates to Anki's scheduling system
**Use case:**
- Schedule cards to appear at specific future dates
- Useful for spaced introduction of content
- Could stagger card introduction based on difficulty

**JSON Example:**
```json
{
  "front": "Advanced topic to study later",
  "back": "Complex explanation",
  "due": 7
}
```

## **Additional Fields That Could Be Useful**

### **4. Custom Model Support**
**Current limitation:** Script hardcodes `genanki.BASIC_MODEL`
**Potential improvement:** Allow custom card templates/models
**Source:** genanki documentation shows Model creation capabilities
**Use case:**
- Cloze deletion cards
- Cards with images/audio
- Custom styling and layouts

### **5. Media File References**
**What it is:** References to audio/image files
**Source:** genanki README "Media Files" section
**Use case:**
- Audio pronunciation for language learning
- Images for visual subjects
- Mathematical formulas as images

## **Ranking by Practicality**

### **Most Useful to Implement:**
1. **`guid`** - Critical for deck updates and preventing duplicates
2. **`sort_field`** - Helpful for organization in large decks

### **Moderately Useful:**
3. **`due`** - Good for spaced content introduction
4. **Custom models** - Advanced but powerful for specialized content

### **Specialized Use Cases:**
5. **Media files** - Important for specific subjects but complex to implement

## **Implementation Considerations**

**For `guid`:**
- Could auto-generate from content hash or allow manual specification
- Most valuable for preventing duplicate imports

**For `sort_field`:**
- Simple to implement, just pass through the parameter
- Could default to front field if not specified

**For `due`:**
- Would need date parsing logic
- Most useful for educational sequences

The **tags** feature we already implemented is actually one of the most practical and commonly used optional features. The next most valuable would likely be **guid** support for preventing duplicates during deck regeneration.

---
*Research conducted: June 28, 2025*
*genanki version: 0.13.1 (confirmed via PyPI)*
