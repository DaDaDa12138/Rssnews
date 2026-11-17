/* global hljs */
// django-pipeline wraps each bundle in its own IIFE (JS_WRAPPER), so a top-level
// `var` in the vendor bundle is private to that bundle. highlight.js is the one
// vendor library that publishes only a lexical `hljs`; the reader bundle calls it
// directly when it renders a code block. Export it on window so splitting vendor
// from application code keeps that call working.
if (typeof hljs !== "undefined") {
    window.hljs = hljs;
}
