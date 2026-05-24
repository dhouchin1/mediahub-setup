# Homebrew formula for mediahub-setup.
#
# This file lives in the source repo as a template.
# To publish a tap:
#
#   1. Create a new GitHub repo named  dhouchin/homebrew-mediahub
#   2. After each PyPI release, update the url + sha256 below and push.
#   3. Users install with:
#        brew tap dhouchin/mediahub
#        brew install mediahub-setup
#
# Generating sha256 after a release:
#   curl -sL <sdist_url> | shasum -a 256
#
# Generating resource blocks (fill in all pip deps):
#   pip install poet
#   poet mediahub-setup
#
# NOTE: Because mediahub-setup is a pure-Python CLI app, the simpler
# approach for most users is:
#   brew install pipx && pipx install mediahub-setup
# The formula below is for users who prefer a managed brew install.

class MediahubSetup < Formula
  include Language::Python::Virtualenv

  desc "Web-wizard installer for a self-hosted Sonarr/Radarr/Prowlarr/qBittorrent stack"
  homepage "https://github.com/dhouchin/mediahub-setup"
  # TODO: update url + sha256 after first PyPI release
  url "https://files.pythonhosted.org/packages/source/m/mediahub-setup/mediahub_setup-0.1.0.tar.gz"
  sha256 "REPLACE_AFTER_FIRST_PYPI_RELEASE"
  license "MIT"
  head "https://github.com/dhouchin/mediahub-setup.git", branch: "main"

  depends_on "python@3.12"

  # Run `poet mediahub-setup` after first PyPI publish to generate these blocks.
  # Example shape — values are placeholders:
  resource "flask" do
    url "https://files.pythonhosted.org/packages/source/f/flask/flask-3.1.1.tar.gz"
    sha256 "REPLACE"
  end

  resource "waitress" do
    url "https://files.pythonhosted.org/packages/source/w/waitress/waitress-3.0.1.tar.gz"
    sha256 "REPLACE"
  end

  resource "click" do
    url "https://files.pythonhosted.org/packages/source/c/click/click-8.1.8.tar.gz"
    sha256 "REPLACE"
  end

  resource "requests" do
    url "https://files.pythonhosted.org/packages/source/r/requests/requests-2.32.3.tar.gz"
    sha256 "REPLACE"
  end

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/source/p/pyyaml/pyyaml-6.0.2.tar.gz"
    sha256 "REPLACE"
  end

  # Flask transitive deps — fill in after `poet` run
  resource "werkzeug" do
    url "REPLACE"
    sha256 "REPLACE"
  end

  resource "jinja2" do
    url "REPLACE"
    sha256 "REPLACE"
  end

  resource "markupsafe" do
    url "REPLACE"
    sha256 "REPLACE"
  end

  resource "itsdangerous" do
    url "REPLACE"
    sha256 "REPLACE"
  end

  resource "blinker" do
    url "REPLACE"
    sha256 "REPLACE"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "mediahub-setup", shell_output("#{bin}/mediahub-setup --help")
  end
end
