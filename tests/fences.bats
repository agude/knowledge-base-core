#!/usr/bin/env bats
#
# Fenced code blocks must not be parsed for headings. A `# comment` inside
# a bash block used to register as an H1, which invented topics in `toc`
# and truncated `section` at the first commented command.

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

FENCED='# Shell Recipes

## Dangling symlinks

```bash
# All dangling symlinks in $HOME
find "$HOME" -xtype l

# Same, restricted to one repo
find "$HOME" -xtype l -lname "*repo*"
```

Trailing prose in the same section.

## Second Section

Content.'

@test "toc ignores comments inside fenced blocks" {
    create_test_article "recipes.md" "$FENCED"
    run "$SCRIPTS/toc" --depth 2
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Shell Recipes"* ]]
    [[ "$output" == *"1. Dangling symlinks"* ]]
    [[ "$output" == *"2. Second Section"* ]]
    [[ "$output" != *"All dangling symlinks"* ]]
    [[ "$output" != *"Same, restricted"* ]]
}

@test "section returns the whole section past a fenced comment" {
    create_test_article "recipes.md" "$FENCED"
    run "$SCRIPTS/section" --file knowledge/recipes.md --heading "Dangling symlinks"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"find \"\$HOME\" -xtype l"* ]]
    [[ "$output" == *"Trailing prose in the same section"* ]]
    [[ "$output" != *"## Second Section"* ]]
}

@test "fenced comments do not shift H2 numbering" {
    create_test_article "recipes.md" "$FENCED"
    run "$SCRIPTS/section" --file knowledge/recipes.md --number 2
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"## Second Section"* ]]
}

@test "tilde fences are honored" {
    create_test_article "tilde.md" '# Tilde

## One

~~~
# not a heading
~~~

Body text.

## Two

More.'
    run "$SCRIPTS/toc" --depth 2
    [[ "$output" == *"1. One"* ]]
    [[ "$output" == *"2. Two"* ]]
    [[ "$output" != *"not a heading"* ]]
}

@test "a longer closing fence closes the block" {
    create_test_article "nested.md" '# Nested

## One

````markdown
```
# still inside
```
````

## Two

Content.'
    run "$SCRIPTS/toc" --depth 2
    [[ "$output" == *"1. One"* ]]
    [[ "$output" == *"2. Two"* ]]
    [[ "$output" != *"still inside"* ]]
}

@test "an unclosed fence swallows the rest of the file" {
    create_test_article "unclosed.md" '# Unclosed

## One

```bash
# comment

## Two'
    run "$SCRIPTS/toc" --depth 2
    [[ "$output" == *"1. One"* ]]
    [[ "$output" != *"2. Two"* ]]
}

@test "fence state resets between files" {
    create_test_article "a.md" '# A

## Open

```bash
# unterminated'
    create_test_article "b.md" '# B

## Visible

Content.'
    run "$SCRIPTS/toc" --depth 2
    [[ "$output" == *"1. Open"* ]]
    [[ "$output" == *"1. Visible"* ]]
}

@test "indented fences up to three spaces are honored" {
    create_test_article "indented.md" '# Indented

## One

   ```bash
   # not a heading
   ```

## Two

Content.'
    run "$SCRIPTS/toc" --depth 2
    [[ "$output" == *"1. One"* ]]
    [[ "$output" == *"2. Two"* ]]
    [[ "$output" != *"not a heading"* ]]
}
