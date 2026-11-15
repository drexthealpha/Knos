# The playground's starter task: print the words of one line in reverse order, one space between them.
#
#     input:   the quick brown fox        output:   fox brown quick the
#
# As it is, this prints the line as it came. Change the last line, open a pull request with "Closes #<the task's
# number>" in its description, and the checks in .knos/acceptance/<number>/ run this file and compare what it prints.
import sys

words = sys.stdin.readline().split()
print(" ".join(reversed(words)))
