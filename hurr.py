from argparse import ArgumentParser
import logging

from os import sep

from hurr_durr import ChanWatcher, FileHandler


def main():
    parser = ArgumentParser(description='Scrape some 4chan.')
    parser.add_argument('-d', '--directory', type=str, required=True,
                        help='the file root to output the scraped content to')
    parser.add_argument('-b', '--board', type=str, required=True, help='the board to scrape')
    parser.add_argument('-i', '--images', action='store_true', help='if given, images will be downloaded as well')
    parser.add_argument('-v', '--verbose', action='store_true', help='output info about stuff going on')
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(format='%(asctime)-15s %(levelname)s %(message)s', level=logging.INFO)

    if args.directory.endswith(sep):
        args.directory = args.directory[:len(sep)]

    watcher = ChanWatcher(FileHandler(args.directory), args.board, args.images)
    watcher.start()


if __name__ == '__main__':
    main()
