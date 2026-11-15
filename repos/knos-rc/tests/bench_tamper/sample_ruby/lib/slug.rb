# The sample project: issue 1 is that slugify keeps punctuation.
module Slug
  KNOWN = [["Hello World", "hello-world"], ["a  b", "a-b"], ["x", "x"]].freeze

  def self.slugify(s)
    s.downcase.split.join("-")
  end
end
