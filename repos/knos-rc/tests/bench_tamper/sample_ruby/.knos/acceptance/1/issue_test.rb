require "test_helper"

class IssueTest < Minitest::Test
  def test_punctuation
    assert_equal "hello-world", Slug.slugify("Hello, World!")
  end

  def test_mixed
    assert_equal "rock-roll-2", Slug.slugify("  Rock & Roll -- 2  ")
  end
end
