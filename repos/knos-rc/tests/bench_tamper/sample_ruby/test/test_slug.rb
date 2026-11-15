require "test_helper"

class SlugTest < Minitest::Test
  Slug::KNOWN.each_with_index do |(s, want), i|
    define_method("test_known_#{i}") { assert_equal want, Slug.slugify(s) }
  end

  def test_empty
    assert_equal "", Slug.slugify("")
  end
end
