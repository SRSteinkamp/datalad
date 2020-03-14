# emacs: -*- mode: python; py-indent-offset: 4; tab-width: 4; indent-tabs-mode: nil -*-
# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the datalad package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
""" utility classes for repositories

"""

import logging

from .exceptions import InvalidInstanceRequestError
from . import path as op
from .network import RI
from .. import utils as ut

lgr = logging.getLogger('datalad.repo')


class Flyweight(type):
    """Metaclass providing an implementation of the flyweight pattern.

    Since the flyweight is very similar to a singleton, we occasionally use this
    term to make clear there's only one instance (at a time).
    This integrates the "factory" into the actual classes, which need
    to have a class attribute `_unique_instances` (WeakValueDictionary).
    By providing an implementation of __call__, you don't need to call a
    factory's get_xy_repo() method to get a singleton. Instead this is called
    when you simply instantiate via MyClass(). So, you basically don't even need
    to know there were singletons. Therefore it is also less likely to sabotage
    the concept by not being aware of how to get an appropriate object.

    Multiple instances, pointing to the same physical repository can cause a
    lot of trouble. This is why this class exists. You should be very aware of
    the implications, if you want to circumvent that mechanism.

    To use this pattern, you need to add this class as a metaclass to the class
    you want to use it with. Additionally there needs to be a class attribute
    `_unique_instances`, which should be a `WeakValueDictionary`. Furthermore
    implement `_flyweight_id_from_args` method to determine, what should be the
    identifying criteria to consider two requested instances the same.

    Example:

    from weakref import WeakValueDictionary

    class MyFlyweightClass(object, metaclass=Flyweight):

        _unique_instances = WeakValueDictionary()

        @classmethod
        def _flyweight_id_from_args(cls, *args, **kwargs):

            id = kwargs.pop('id')
            return id, args, kwargs

        def __init__(self, some, someother=None):
            pass

    a = MyFlyweightClass('bla', id=1)
    b = MyFlyweightClass('blubb', id=1)
    assert a is b
    c = MyFlyweightClass('whatever', id=2)
    assert c is not a
    """

    def _flyweight_id_from_args(cls, *args, **kwargs):
        """create an ID from arguments passed to `__call__`

        Subclasses need to implement this method. The ID it returns is used to
        determine whether or not there already is an instance of that kind and
        as key in the `_unique_instances` dictionary.

        Besides the ID this should return args and kwargs, which can be modified
        herein and will be passed on to the constructor of a requested instance.

        Parameters
        ----------
        args:
         positional arguments passed to __call__
        kwargs:
         keyword arguments passed to __call__

        Returns
        -------
        hashable, args, kwargs
          id, optionally manipulated args and kwargs to be passed to __init__
        """
        raise NotImplementedError

    #       TODO: - We might want to remove the classmethod from Flyweight altogether and replace by an
    #             requirement to implement an actual method, since the purpose of it is actually about a
    #             particular, existing instance
    #             - Done. But update docs!
    # def _flyweight_invalid(cls, id):
    #     """determines whether or not an instance with `id` became invalid and
    #     therefore has to be instantiated again.
    #
    #     Subclasses can implement this method to provide an additional condition
    #     on when to create a new instance besides there is none yet.
    #
    #     Parameter
    #     ---------
    #     id: hashable
    #       ID of the requested instance
    #
    #     Returns
    #     -------
    #     bool
    #       whether to consider an existing instance with that ID invalid and
    #       therefore create a new instance. Default implementation always returns
    #       False.
    #     """
    #     return False

    def _flyweight_reject(cls, id, *args, **kwargs):
        """decides whether to reject a request for an instance

        This gives the opportunity to detect a conflict of an instance request
        with an already existing instance, that is not invalidated by
        `_flyweight_invalid`. In case the return value is not `None`, it will be
        used as the message for an `InvalidInstanceRequestError`,
        raised by `__call__`

        Parameters
        ----------
        id: hashable
          the ID of the instance in question as calculated by
          `_flyweight_id_from_args`
        args:
        kwargs:
          (keyword) arguments to the original call

        Returns:
        --------
        None or str
        """
        return None

    def __call__(cls, *args, **kwargs):

        id_, new_args, new_kwargs = cls._flyweight_id_from_args(*args, **kwargs)
        instance = cls._unique_instances.get(id_, None)

        if instance is None or instance._flyweight_invalid():
            # we have no such instance yet or the existing one is invalidated,
            # so we instantiate:
            instance = type.__call__(cls, *new_args, **new_kwargs)
            cls._unique_instances[id_] = instance
        else:
            # we have an instance already that is not invalid itself; check
            # whether there is a conflict, otherwise return existing one:
            # TODO
            # Note, that this might (and probably should) go away, when we
            # decide how to deal with currently possible invalid constructor
            # calls for the repo classes. In particular this is about calling
            # it with different options than before, that might lead to
            # fundamental changes in the repository (like annex repo version
            # change or re-init of git)

            # force? may not mean the same thing
            msg = cls._flyweight_reject(id_, *new_args, **new_kwargs)
            if msg is not None:
                raise InvalidInstanceRequestError(id_, msg)

        return instance


class PathBasedFlyweight(Flyweight):

    def _flyweight_preproc_path(cls, path):
        """perform any desired path preprocessing (e.g., aliases)

        By default nothing is done
        """
        return path

    def _flyweight_postproc_path(cls, path):
        """perform any desired path post-processing (e.g., dereferencing etc)

        By default - realpath to guarantee reuse. Derived classes (e.g.,
        Dataset) could override to allow for symlinked datasets to have
        individual instances for multiple symlinks
        """
        # resolve symlinks to make sure we have exactly one instance per
        # physical repository at a time
        # do absolute() in addition to always get an absolute path
        # even with non-existing paths on windows
        return str(ut.Path(path).resolve().absolute())

    def _flyweight_id_from_args(cls, *args, **kwargs):

        if args:
            # to a certain degree we need to simulate an actual call to __init__
            # and make sure, passed arguments are fitting:
            # TODO: Figure out, whether there is a cleaner way to do this in a
            # generic fashion
            assert('path' not in kwargs)
            path = args[0]
            args = args[1:]
        elif 'path' in kwargs:
            path = kwargs.pop('path')
        else:
            raise TypeError("__init__() requires argument `path`")

        if path is None:
            lgr.debug("path is None. args: %s, kwargs: %s", args, kwargs)
            raise ValueError("path must not be None")

        # Custom handling for few special abbreviations if defined by the class
        path_ = cls._flyweight_preproc_path(path)

        # mirror what is happening in __init__
        if isinstance(path, ut.PurePath):
            path = str(path)

        # Sanity check for argument `path`:
        # raise if we cannot deal with `path` at all or
        # if it is not a local thing:
        localpath = RI(path_).localpath

        path_postproc = cls._flyweight_postproc_path(localpath)

        kwargs['path'] = path_postproc
        return path_postproc, args, kwargs
    # End Flyweight



# TODO: see issue #1100
class RepoInterface(object):
    """common operations for annex and plain git repositories

    Especially provides "annex operations" on plain git repos, that just do
    (or return) the "right thing"
    """

    # Note: Didn't find a way yet, to force GitRepo as well as AnnexRepo to
    # implement a method defined herein, since AnnexRepo inherits from GitRepo.
    # Would be much nicer, but still - I'd prefer to have a central place for
    # these anyway.

    # Note 2: Seems possible. There is MRO magic:
    # http://pybites.blogspot.de/2009/01/mro-magic.html
    # http://stackoverflow.com/questions/20822850/change-python-mro-at-runtime

    # Test!
    pass
