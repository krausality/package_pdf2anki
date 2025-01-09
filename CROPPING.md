Below is an example implementation that adds support for **optional cropping** of up to 4 rectangular areas per page. Each rectangle is specified by its top-left and bottom-right pixel coordinates once the page has been rendered to an image. If you supply **no** rectangles, you will just get the full-page PNG(s). If you supply one or more rectangles, you will additionally get cropped PNG files for each rectangle. 

---

### How to specify rectangles on the command line

This example assumes you pass each rectangle’s coordinates as a comma-separated string. For example, if you want to crop two rectangles:

```bash
python pdf2pic.py mydoc.pdf out "100,150,300,400" "350,450,500,600"
```

- `100,150,300,400` means top-left = (100, 150), bottom-right = (300, 400).
- `350,450,500,600` means top-left = (350, 450), bottom-right = (500, 600).

You can pass up to four such strings:

```bash
python pdf2pic.py mydoc.pdf out "x1,y1,x2,y2" "x1,y1,x2,y2" "x1,y1,x2,y2" "x1,y1,x2,y2"
```

If no coordinates are provided, the script will behave exactly as before, saving only the uncropped page images.

---
