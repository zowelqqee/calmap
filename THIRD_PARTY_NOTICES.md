# Third-party notices

## MuscleMap

The anatomical artwork behind the workout muscle map — the four models in
`mobile/lib/widgets/anatomy_paths.dart` (male and female, front and back) —
comes from the **MuscleMap** project.

    MuscleMap
    Copyright (c) 2026 Melih Colpan
    https://github.com/melihcolpan/MuscleMap

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

### Changes made

* The Swift path tables (`Sources/MuscleMap/Data/*Paths.swift`) were converted
  to Dart maps of slug to sub-paths, with the project's `common`, `left` and
  `right` lists concatenated; the path data and the view boxes are unchanged.
* Nothing else from the project is used — the SVG parsing, the rendering, the
  mapping of slugs onto Calmap's Russian muscle vocabulary and the load
  colouring are Calmap's own code.
