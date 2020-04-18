# ex: set sts=4 ts=4 sw=4 noet:
# -*- coding: utf-8 -*-
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the datalad package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""

"""

import logging
import os
from os.path import exists
from os.path import join as opj

from unittest.mock import patch
from datalad.tests.utils import (
    assert_raises,
    assert_false,
    assert_true,
    assert_equal,
    assert_not_equal,
    assert_in,
    assert_not_in,
    ok_file_has_content,
    with_tree,
    with_tempfile,
    with_testsui,
    chpwd,
)
from datalad.utils import swallow_logs

from datalad.distribution.dataset import Dataset
from datalad.api import create
from datalad.config import (
    ConfigManager,
    rewrite_url,
)
from datalad.cmd import CommandError

from datalad.support.external_versions import external_versions

# XXX tabs are intentional (part of the format)!
# XXX put back! confuses pep8
_config_file_content = """\
[something]
user = name=Jane Doe
user = email=jd@example.com
novalue
empty =
myint = 3

[onemore "complicated の beast with.dot"]
findme = 5.0
"""

_dataset_config_template = {
    'ds': {
        '.datalad': {
            'config': _config_file_content}}}


@with_tree(tree=_dataset_config_template)
@with_tempfile(mkdir=True)
def test_something(path, new_home):
    # will refuse to work on dataset without a dataset
    assert_raises(ValueError, ConfigManager, source='dataset')
    # now read the example config
    cfg = ConfigManager(Dataset(opj(path, 'ds')), source='dataset')
    assert_equal(len(cfg), 5)
    assert_in('something.user', cfg)
    # multi-value
    assert_equal(len(cfg['something.user']), 2)
    assert_equal(cfg['something.user'], ('name=Jane Doe', 'email=jd@example.com'))

    assert_true(cfg.has_section('something'))
    assert_false(cfg.has_section('somethingelse'))
    assert_equal(sorted(cfg.sections()),
                 [u'onemore.complicated の beast with.dot', 'something'])
    assert_true(cfg.has_option('something', 'user'))
    assert_false(cfg.has_option('something', 'us?er'))
    assert_false(cfg.has_option('some?thing', 'user'))
    assert_equal(sorted(cfg.options('something')), ['empty', 'myint', 'novalue', 'user'])
    assert_equal(cfg.options(u'onemore.complicated の beast with.dot'), ['findme'])

    assert_equal(
        sorted(cfg.items()),
        [(u'onemore.complicated の beast with.dot.findme', '5.0'),
         ('something.empty', ''),
         ('something.myint', '3'),
         ('something.novalue', None),
         ('something.user', ('name=Jane Doe', 'email=jd@example.com'))])
    assert_equal(
        sorted(cfg.items('something')),
        [('something.empty', ''),
         ('something.myint', '3'),
         ('something.novalue', None),
         ('something.user', ('name=Jane Doe', 'email=jd@example.com'))])

    # always get all values
    assert_equal(
        cfg.get('something.user'),
        ('name=Jane Doe', 'email=jd@example.com'))
    assert_raises(KeyError, cfg.__getitem__, 'somedthing.user')
    assert_equal(cfg.getfloat(u'onemore.complicated の beast with.dot', 'findme'), 5.0)
    assert_equal(cfg.getint('something', 'myint'), 3)
    assert_equal(cfg.getbool('something', 'myint'), True)
    # git demands a key without value at all to be used as a flag, thus True
    assert_equal(cfg.getbool('something', 'novalue'), True)
    assert_equal(cfg.get('something.novalue'), None)
    # empty value is False
    assert_equal(cfg.getbool('something', 'empty'), False)
    assert_equal(cfg.get('something.empty'), '')
    assert_equal(cfg.getbool('doesnot', 'exist', default=True), True)
    assert_raises(TypeError, cfg.getbool, 'something', 'user')

    # gitpython-style access
    assert_equal(cfg.get('something.myint'), cfg.get_value('something', 'myint'))
    assert_equal(cfg.get_value('doesnot', 'exist', default='oohaaa'), 'oohaaa')
    # weired, but that is how it is
    assert_raises(KeyError, cfg.get_value, 'doesnot', 'exist', default=None)

    # modification follows
    cfg.add('something.new', 'の')
    assert_equal(cfg.get('something.new'), u'の')
    # sections are added on demand
    cfg.add('unheard.of', 'fame')
    assert_true(cfg.has_section('unheard.of'))
    comp = cfg.items('something')
    cfg.rename_section('something', 'this')
    assert_true(cfg.has_section('this'))
    assert_false(cfg.has_section('something'))
    # direct comparision would fail, because of section prefix
    assert_equal(len(cfg.items('this')), len(comp))
    # fail if no such section
    with swallow_logs():
        assert_raises(CommandError, cfg.rename_section, 'nothere', 'irrelevant')
    assert_true(cfg.has_option('this', 'myint'))
    cfg.unset('this.myint')
    assert_false(cfg.has_option('this', 'myint'))

    # batch a changes
    cfg.add('mike.wants.to', 'know', reload=False)
    assert_false('mike.wants.to' in cfg)
    cfg.add('mike.wants.to', 'eat')
    assert_true('mike.wants.to' in cfg)
    assert_equal(len(cfg['mike.wants.to']), 2)

    # set a new one:
    cfg.set('mike.should.have', 'known')
    assert_in('mike.should.have', cfg)
    assert_equal(cfg['mike.should.have'], 'known')
    # set an existing one:
    cfg.set('mike.should.have', 'known better')
    assert_equal(cfg['mike.should.have'], 'known better')
    # set, while there are several matching ones already:
    cfg.add('mike.should.have', 'a meal')
    assert_equal(len(cfg['mike.should.have']), 2)
    # raises with force=False
    assert_raises(CommandError,
                  cfg.set, 'mike.should.have', 'a beer', force=False)
    assert_equal(len(cfg['mike.should.have']), 2)
    # replaces all matching ones with force=True
    cfg.set('mike.should.have', 'a beer', force=True)
    assert_equal(cfg['mike.should.have'], 'a beer')

    # fails unknown location
    assert_raises(ValueError, cfg.add, 'somesuch', 'shit', where='umpalumpa')

    # very carefully test non-local config
    # so carefully that even in case of bad weather Yarik doesn't find some
    # lame datalad unittest sections in his precious ~/.gitconfig
    with patch.dict('os.environ',
                    {'HOME': new_home, 'DATALAD_SNEAKY_ADDITION': 'ignore'}):
        global_gitconfig = opj(new_home, '.gitconfig')
        assert(not exists(global_gitconfig))
        globalcfg = ConfigManager()
        assert_not_in('datalad.unittest.youcan', globalcfg)
        assert_in('datalad.sneaky.addition', globalcfg)
        cfg.add('datalad.unittest.youcan', 'removeme', where='global')
        assert(exists(global_gitconfig))
        # it did not go into the dataset's config!
        assert_not_in('datalad.unittest.youcan', cfg)
        # does not monitor additions!
        globalcfg.reload(force=True)
        assert_in('datalad.unittest.youcan', globalcfg)
        with swallow_logs():
            assert_raises(
                CommandError,
                globalcfg.unset,
                'datalad.unittest.youcan',
                where='local')
        assert(globalcfg.has_section('datalad.unittest'))
        globalcfg.unset('datalad.unittest.youcan', where='global')
        # but after we unset the only value -- that section is no longer listed
        assert (not globalcfg.has_section('datalad.unittest'))
        assert_not_in('datalad.unittest.youcan', globalcfg)
        if external_versions['cmd:git'] < '2.18':
            # older versions leave empty section behind in the file
            ok_file_has_content(global_gitconfig, '[datalad "unittest"]', strip=True)
            # remove_section to clean it up entirely
            globalcfg.remove_section('datalad.unittest', where='global')
        ok_file_has_content(global_gitconfig, "")

    cfg = ConfigManager(
        Dataset(opj(path, 'ds')),
        source='dataset',
        overrides={'datalad.godgiven': True})
    assert_equal(cfg.get('datalad.godgiven'), True)
    # setter has no effect
    cfg.set('datalad.godgiven', 'false')
    assert_equal(cfg.get('datalad.godgiven'), True)


@with_tree(tree={
    'ds': {
        '.datalad': {
            'config': """\
[crazy]
    fa = !git remote | xargs -r -I REMOTE /bin/bash -c 'echo I: Fetching from REMOTE && git fetch --prune REMOTE && git fetch -t REMOTE' && [ -d .git/svn ] && bash -c 'echo I: Fetching from SVN && git svn fetch' || : && [ -e .gitmodules ] && bash -c 'echo I: Fetching submodules && git submodule foreach git fa' && [ -d .git/sd ] && bash -c 'echo I: Fetching bugs into sd && git-sd pull --all' || :
    pa = !git paremotes | tr ' ' '\\n'  | xargs -r -l1 git push
    pt = !git testremotes | tr ' ' '\\n'  | xargs -r -l1 -I R git push -f R master
    ptdry = !git testremotes | tr ' ' '\\n'  | xargs -r -l1 -I R git push -f --dry-run R master
    padry = !git paremotes | tr ' ' '\\n' | xargs -r -l1 git push --dry-run
"""}}})
def test_crazy_cfg(path):
    cfg = ConfigManager(Dataset(opj(path, 'ds')), source='dataset')
    assert_in('crazy.padry', cfg)
    # make sure crazy config is not read when in local mode
    cfg = ConfigManager(Dataset(opj(path, 'ds')), source='local')
    assert_not_in('crazy.padry', cfg)
    # it will make it in in 'any' mode though
    cfg = ConfigManager(Dataset(opj(path, 'ds')), source='any')
    assert_in('crazy.padry', cfg)
    # typos in the source mode arg will not have silent side-effects
    assert_raises(
        ValueError, ConfigManager, Dataset(opj(path, 'ds')), source='locale')


@with_tempfile
def test_obtain(path):
    ds = create(path)
    cfg = ConfigManager(ds)
    dummy = 'datalad.test.dummy'
    # we know nothing and we don't know how to ask
    assert_raises(RuntimeError, cfg.obtain, dummy)
    # can report known ones
    cfg.add(dummy, '5.3')
    assert_equal(cfg.obtain(dummy), '5.3')
    # better type
    assert_equal(cfg.obtain(dummy, valtype=float), 5.3)
    # don't hide type issues, float doesn't become an int magically
    assert_raises(ValueError, cfg.obtain, dummy, valtype=int)
    # inject some prior knowledge
    from datalad.interface.common_cfg import definitions as cfg_defs
    cfg_defs[dummy] = dict(type=float)
    # no we don't need to specify a type anymore
    assert_equal(cfg.obtain(dummy), 5.3)
    # but if we remove the value from the config, all magic is gone
    cfg.unset(dummy)
    # we know nothing and we don't know how to ask
    assert_raises(RuntimeError, cfg.obtain, dummy)

    #
    # test actual interaction
    #
    @with_testsui()
    def ask():
        # fail on unkown dialog type
        assert_raises(ValueError, cfg.obtain, dummy, dialog_type='Rorschach_test')
    ask()

    # ask nicely, and get a value of proper type using the preconfiguration
    @with_testsui(responses='5.3')
    def ask():
        assert_equal(
            cfg.obtain(dummy, dialog_type='question', text='Tell me'), 5.3)
    ask()

    # preconfigure even more, to get the most compact call
    cfg_defs[dummy]['ui'] = ('question', dict(text='tell me', title='Gretchen Frage'))

    @with_testsui(responses='5.3')
    def ask():
        assert_equal(cfg.obtain(dummy), 5.3)
    ask()

    @with_testsui(responses='murks')
    def ask():
        assert_raises(ValueError, cfg.obtain, dummy)
    ask()

    # fail to store when destination is not specified, will not even ask
    @with_testsui()
    def ask():
        assert_raises(ValueError, cfg.obtain, dummy, store=True)
    ask()

    # but we can preconfigure it
    cfg_defs[dummy]['destination'] = 'broken'

    @with_testsui(responses='5.3')
    def ask():
        assert_raises(ValueError, cfg.obtain, dummy, store=True)
    ask()

    # fixup destination
    cfg_defs[dummy]['destination'] = 'dataset'

    @with_testsui(responses='5.3')
    def ask():
        assert_equal(cfg.obtain(dummy, store=True), 5.3)
    ask()

    # now it won't have to ask again
    @with_testsui()
    def ask():
        assert_equal(cfg.obtain(dummy), 5.3)
    ask()

    # wipe it out again
    cfg.unset(dummy)
    assert_not_in(dummy, cfg)

    # XXX cannot figure out how I can simulate a simple <Enter>
    ## respond with accepting the default
    #@with_testsui(responses=...)
    #def ask():
    #    assert_equal(cfg.obtain(dummy, default=5.3), 5.3)
    #ask()


def test_from_env():
    cfg = ConfigManager()
    assert_not_in('datalad.crazy.cfg', cfg)
    os.environ['DATALAD_CRAZY_CFG'] = 'impossibletoguess'
    cfg.reload()
    assert_in('datalad.crazy.cfg', cfg)
    assert_equal(cfg['datalad.crazy.cfg'], 'impossibletoguess')
    # not in dataset-only mode
    cfg = ConfigManager(Dataset('nowhere'), source='dataset')
    assert_not_in('datalad.crazy.cfg', cfg)
    # check env trumps override
    cfg = ConfigManager()
    assert_not_in('datalad.crazy.override', cfg)
    cfg.set('datalad.crazy.override', 'fromoverride', where='override')
    cfg.reload()
    assert_equal(cfg['datalad.crazy.override'], 'fromoverride')
    os.environ['DATALAD_CRAZY_OVERRIDE'] = 'fromenv'
    cfg.reload()
    assert_equal(cfg['datalad.crazy.override'], 'fromenv')


def test_overrides():
    cfg = ConfigManager()
    # any sensible (and also our CI) test environment(s) should have this
    assert_in('user.name', cfg)
    # set
    cfg.set('user.name', 'myoverride', where='override')
    assert_equal(cfg['user.name'], 'myoverride')
    # unset just removes override, not entire config
    cfg.unset('user.name', where='override')
    assert_in('user.name', cfg)
    assert_not_equal('user.name', 'myoverride')
    # add
    # there is no initial increment
    cfg.add('user.name', 'myoverride', where='override')
    assert_equal(cfg['user.name'], 'myoverride')
    # same as with add, not a list
    assert_equal(cfg['user.name'], 'myoverride')
    # but then there is
    cfg.add('user.name', 'myother', where='override')
    assert_equal(cfg['user.name'], ['myoverride', 'myother'])
    # rename
    assert_not_in('ups.name', cfg)
    cfg.rename_section('user', 'ups', where='override')
    # original variable still there
    assert_in('user.name', cfg)
    # rename of override in effect
    assert_equal(cfg['ups.name'], ['myoverride', 'myother'])
    # remove entirely by section
    cfg.remove_section('ups', where='override')
    from datalad.utils import Path
    assert_not_in(
        'ups.name', cfg,
        (cfg._store,
         cfg.overrides,
         cfg._cfgfiles,
         [Path(f).read_text() for f in cfg._cfgfiles if Path(f).exists()],
    ))


def test_rewrite_url():
    test_cases = (
        # no match
        ('unicorn', 'unicorn'),
        # custom label replacement
        ('example:datalad/datalad.git', 'git@example.com:datalad/datalad.git'),
        # protocol enforcement
        ('git://example.com/some', 'https://example.com/some'),
        # multi-match
        ('mylabel', 'ria+ssh://fully.qualified.com'),
        ('myotherlabel', 'ria+ssh://fully.qualified.com'),
        # conflicts, same label pointing to different URLs
        ('conflict', 'conflict'),
        # also conflicts, but hidden in a multi-value definition
        ('conflict2', 'conflict2'),
    )
    cfg_in = {
        # label rewrite
        'git@example.com:': 'example:',
        # protocol change
        'https://example': 'git://example',
        # multi-value
        'ria+ssh://fully.qualified.com': ('mylabel', 'myotherlabel'),
        # conflicting definitions
        'http://host1': 'conflict',
        'http://host2': 'conflict',
        # hidden conflict
        'http://host3': 'conflict2',
        'http://host4': ('someokish', 'conflict2'),
    }
    cfg = {
        'url.{}.insteadof'.format(k): v
        for k, v in cfg_in.items()
    }
    for input, output in test_cases:
        with swallow_logs(logging.WARNING) as msg:
            assert_equal(rewrite_url(cfg, input), output)
        if input.startswith('conflict'):
            assert_in("Ignoring URL rewrite", msg.out)


# https://github.com/datalad/datalad/issues/4071
@with_tempfile()
@with_tempfile()
def test_no_leaks(path1, path2):
    ds1 = Dataset(path1).create()
    ds1.config.set('i.was.here', 'today', where='local')
    assert_in('i.was.here', ds1.config.keys())
    ds1.config.reload()
    assert_in('i.was.here', ds1.config.keys())
    # now we move into this one repo, and create another
    # make sure that no config from ds1 leaks into ds2
    with chpwd(path1):
        ds2 = Dataset(path2)
        assert_not_in('i.was.here', ds2.config.keys())
        ds2.config.reload()
        assert_not_in('i.was.here', ds2.config.keys())

        ds2.create()
        assert_not_in('i.was.here', ds2.config.keys())

        # and that we do not track the wrong files
        assert_not_in(opj(ds1.path, '.git', 'config'), ds2.config._cfgfiles)
        assert_not_in(opj(ds1.path, '.datalad', 'config'), ds2.config._cfgfiles)
        # these are the right ones
        assert_in(opj(ds2.path, '.git', 'config'), ds2.config._cfgfiles)
        assert_in(opj(ds2.path, '.datalad', 'config'), ds2.config._cfgfiles)


@with_tempfile()
def test_no_local_write_if_no_dataset(path):
    Dataset(path).create()
    with chpwd(path):
        cfg = ConfigManager()
        with assert_raises(CommandError):
            cfg.set('a.b.c', 'd', where='local')


@with_tempfile
def test_dataset_local_mode(path):
    ds = create(path)
    # any sensible (and also our CI) test environment(s) should have this
    assert_in('user.name', ds.config)
    # from .datalad/config
    assert_in('datalad.dataset.id', ds.config)
    # from .git/config
    assert_in('annex.version', ds.config)
    # now check that dataset-local mode doesn't have the global piece
    cfg = ConfigManager(ds, source='dataset-local')
    assert_not_in('user.name', cfg)
    assert_in('datalad.dataset.id', cfg)
    assert_in('annex.version', cfg)


# https://github.com/datalad/datalad/issues/4071
@with_tempfile
def test_dataset_systemglobal_mode(path):
    ds = create(path)
    # any sensible (and also our CI) test environment(s) should have this
    assert_in('user.name', ds.config)
    # from .datalad/config
    assert_in('datalad.dataset.id', ds.config)
    # from .git/config
    assert_in('annex.version', ds.config)
    with chpwd(path):
        # now check that no config from a random dataset at PWD is picked up
        # if not dataset instance was provided
        cfg = ConfigManager(dataset=None, source='any')
        assert_in('user.name', cfg)
        assert_not_in('datalad.dataset.id', cfg)
        assert_not_in('annex.version', cfg)
