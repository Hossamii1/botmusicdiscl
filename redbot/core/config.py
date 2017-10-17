import logging
from copy import deepcopy
from typing import Callable, Union, Tuple

import discord

from .data_manager import cog_data_path, core_data_path
from .drivers.red_json import JSON as JSONDriver

log = logging.getLogger("red.config")


class Value:
    """
    A singular "value" of data.

    .. py:attribute:: identifiers

        This attribute provides all the keys necessary to get a specific data element from a json document.

    .. py:attribute:: default

        The default value for the data element that :py:attr:`identifiers` points at.

    .. py:attribute:: spawner

        A reference to :py:attr:`.Config.spawner`.
    """
    def __init__(self, identifiers: Tuple[str], default_value, spawner):
        self._identifiers = identifiers
        self.default = default_value

        self.spawner = spawner

    @property
    def identifiers(self):
        return tuple(str(i) for i in self._identifiers)

    async def _get(self, default):
        driver = self.spawner.get_driver()
        try:
            ret = await driver.get(self.identifiers)
        except KeyError:
            return default if default is not None else self.default
        return ret

    def __call__(self, default=None):
        """
        Each :py:class:`Value` object is created by the :py:meth:`Group.__getattr__` method.
        The "real" data of the :py:class:`Value` object is accessed by this method. It is a replacement for a
        :python:`get()` method.

        For example::

            foo = await conf.guild(some_guild).foo()

            # Is equivalent to this

            group_obj = conf.guild(some_guild)
            value_obj = conf.foo
            foo = await value_obj()

        .. important::

            This is now, for all intents and purposes, a coroutine.

        :param default:
            This argument acts as an override for the registered default provided by :py:attr:`default`. This argument
            is ignored if its value is :python:`None`.
        :type default: Optional[object]
        :return:
            A coroutine object that must be awaited.
        """
        return self._get(default)

    async def set(self, value):
        """
        Sets the value of the data element indicate by :py:attr:`identifiers`.

        For example::

            # Sets global value "foo" to False
            await conf.foo.set(False)

            # Sets guild specific value of "bar" to True
            await conf.guild(some_guild).bar.set(True)
        """
        driver = self.spawner.get_driver()
        await driver.set(self.identifiers, value)


class Group(Value):
    """
    A "group" of data, inherits from :py:class:`.Value` which means that all of the attributes and methods available
    in :py:class:`.Value` are also available when working with a :py:class:`.Group` object.

    .. py:attribute:: defaults

        A dictionary of registered default values for this :py:class:`Group`.

    .. py:attribute:: force_registration

        See :py:attr:`.Config.force_registration`.
    """
    def __init__(self, identifiers: Tuple[str],
                 defaults: dict,
                 spawner,
                 force_registration: bool=False):
        self._defaults = defaults
        self.force_registration = force_registration
        self.spawner = spawner

        super().__init__(identifiers, {}, self.spawner)

    @property
    def defaults(self):
        return self._defaults.copy()

    # noinspection PyTypeChecker
    def __getattr__(self, item: str) -> Union["Group", Value]:
        """
        Takes in the next accessible item.

         1. If it's found to be a group of data we return another :py:class:`Group` object.
         2. If it's found to be a data value we return a :py:class:`.Value` object.
         3. If it is not found and :py:attr:`force_registration` is :python:`True` then we raise
            :py:exc:`AttributeError`.
         4. Otherwise return a :py:class:`.Value` object.

        :param str item:
            The name of the item a cog is attempting to access through normal Python attribute
            access.
        """
        is_group = self.is_group(item)
        is_value = not is_group and self.is_value(item)
        new_identifiers = self.identifiers + (item, )
        if is_group:
            return Group(
                identifiers=new_identifiers,
                defaults=self._defaults[item],
                spawner=self.spawner,
                force_registration=self.force_registration
            )
        elif is_value:
            return Value(
                identifiers=new_identifiers,
                default_value=self._defaults[item],
                spawner=self.spawner
            )
        elif self.force_registration:
            raise AttributeError(
                "'{}' is not a valid registered Group"
                "or value.".format(item)
            )
        else:
            return Value(
                identifiers=new_identifiers,
                default_value=None,
                spawner=self.spawner
            )

    @property
    def _super_group(self) -> 'Group':
        super_group = Group(
            self.identifiers[:-1],
            defaults={},
            spawner=self.spawner,
            force_registration=self.force_registration
        )
        return super_group

    def is_group(self, item: str) -> bool:
        """
        A helper method for :py:meth:`__getattr__`. Most developers will have no need to use this.

        :param str item:
            See :py:meth:`__getattr__`.
        """
        default = self._defaults.get(item)
        return isinstance(default, dict)

    def is_value(self, item: str) -> bool:
        """
        A helper method for :py:meth:`__getattr__`. Most developers will have no need to use this.

        :param str item:
            See :py:meth:`__getattr__`.
        """
        try:
            default = self._defaults[item]
        except KeyError:
            return False

        return not isinstance(default, dict)

    def get_attr(self, item: str, default=None, resolve=True):
        """
        This is available to use as an alternative to using normal Python attribute access. It is required if you find
        a need for dynamic attribute access.

        .. note::

            Use of this method should be avoided wherever possible.

        A possible use case::

            @commands.command()
            async def some_command(self, ctx, item: str):
                user = ctx.author

                # Where the value of item is the name of the data field in Config
                await ctx.send(await self.conf.user(user).get_attr(item))

        :param str item:
            The name of the data field in :py:class:`.Config`.
        :param default:
            This is an optional override to the registered default for this item.
        :param resolve:
            If this is :code:`True` this function will return a coroutine that resolves to a "real" data value,
            if :code:`False` this function will return an instance of :py:class:`Group` or :py:class:`Value`
            depending on the type of the "real" data value.
        :rtype:
            Coroutine or Value
        """
        value = getattr(self, item)
        if resolve:
            return value(default=default)
        else:
            return value

    async def all(self) -> dict:
        """
        This method allows you to get "all" of a particular group of data. It will return the dictionary of all data
        for a particular Guild/Channel/Role/User/Member etc.

        .. note::

            Any values that have not been set from the registered defaults will have their default values
            added to the dictionary that this method returns.

        :rtype: dict
        """
        defaults = self.defaults
        defaults.update(await self())
        return defaults

    async def set(self, value):
        if not isinstance(value, dict):
            raise ValueError(
                "You may only set the value of a group to be a dict."
            )
        await super().set(value)

    async def set_attr(self, item: str, value):
        """
        Please see :py:meth:`get_attr` for more information.

        .. note::

            Use of this method should be avoided wherever possible.
        """
        value_obj = getattr(self, item)
        await value_obj.set(value)

    async def clear(self):
        """
        Wipes all data from the given Guild/Channel/Role/Member/User. If used on a global group, it will wipe all global
        data.
        """
        await self.set({})


class MemberGroup(Group):
    """
    A specific group class for use with member data only. Inherits from :py:class:`.Group`. In this group data is
    stored as :code:`GUILD_ID -> MEMBER_ID -> data`.
    """
    @property
    def _super_group(self) -> Group:
        new_identifiers = self.identifiers[:2]
        group_obj = Group(
            identifiers=new_identifiers,
            defaults={},
            spawner=self.spawner
        )
        return group_obj

    @property
    def _guild_group(self) -> Group:
        new_identifiers = self.identifiers[:3]
        group_obj = Group(
            identifiers=new_identifiers,
            defaults={},
            spawner=self.spawner
        )
        return group_obj


class Config:
    """
    You should always use :func:`get_conf` or :func:`get_core_conf` to initialize a Config object.

    .. important::
        Most config data should be accessed through its respective group method (e.g. :py:meth:`guild`)
        however the process for accessing global data is a bit different. There is no :python:`global` method
        because global data is accessed by normal attribute access::

            await conf.foo()

    .. py:attribute:: cog_name

        The name of the cog that has requested a :py:class:`.Config` object.

    .. py:attribute:: unique_identifier

        Unique identifier provided to differentiate cog data when name conflicts occur.

    .. py:attribute:: spawner

        A callable object that returns some driver that implements :py:class:`.drivers.red_base.BaseDriver`.

    .. py:attribute:: force_registration

        A boolean that determines if :py:class:`.Config` should throw an error if a cog attempts to access an attribute
        which has not been previously registered.

        .. note::

            **You should use this.** By enabling force registration you give :py:class:`.Config` the ability to alert
            you instantly if you've made a typo when attempting to access data.
    """
    GLOBAL = "GLOBAL"
    GUILD = "GUILD"
    CHANNEL = "TEXTCHANNEL"
    ROLE = "ROLE"
    USER = "USER"
    MEMBER = "MEMBER"

    def __init__(self, cog_name: str, unique_identifier: str,
                 driver_spawn: Callable,
                 force_registration: bool=False,
                 defaults: dict=None):
        self.cog_name = cog_name
        self.unique_identifier = unique_identifier

        self.spawner = driver_spawn
        self.force_registration = force_registration
        self._defaults = defaults or {}

    @property
    def defaults(self):
        return self._defaults.copy()

    @classmethod
    def get_conf(cls, cog_instance, identifier: int,
                 force_registration=False):
        """
        Returns a Config instance based on a simplified set of initial
        variables.

        :param cog_instance:
        :param identifier:
            Any random integer, used to keep your data
            distinct from any other cog with the same name.
        :param force_registration:
            Should config require registration
            of data keys before allowing you to get/set values?
        :return:
            A new config object.
        """
        cog_path_override = cog_data_path(cog_instance)
        cog_name = cog_path_override.stem
        uuid = str(hash(identifier))

        spawner = JSONDriver(cog_name, data_path_override=cog_path_override)
        return cls(cog_name=cog_name, unique_identifier=uuid,
                   force_registration=force_registration,
                   driver_spawn=spawner)

    @classmethod
    def get_core_conf(cls, force_registration: bool=False):
        """
        All core modules that require a config instance should use this classmethod instead of
        :py:meth:`get_conf`

        :param int identifier:
            See :py:meth:`get_conf`
        :param force_registration:
            See :py:attr:`force_registration`
        :type force_registration: Optional[bool]
        """
        driver_spawn = JSONDriver("Core", data_path_override=core_data_path())
        return cls(cog_name="Core", driver_spawn=driver_spawn,
                   unique_identifier='0',
                   force_registration=force_registration)

    def __getattr__(self, item: str) -> Union[Group, Value]:
        """
        This is used to generate Value or Group objects for global
            values.
        :param item:
        :return:
        """
        global_group = self._get_base_group(self.GLOBAL)
        return getattr(global_group, item)

    @staticmethod
    def _get_defaults_dict(key: str, value) -> dict:
        """
        Since we're allowing nested config stuff now, not storing the
            _defaults as a flat dict sounds like a good idea. May turn
            out to be an awful one but we'll see.
        :param key:
        :param value:
        :return:
        """
        ret = {}
        partial = ret
        splitted = key.split('__')
        for i, k in enumerate(splitted, start=1):
            if not k.isidentifier():
                raise RuntimeError("'{}' is an invalid config key.".format(k))
            if i == len(splitted):
                partial[k] = value
            else:
                partial[k] = {}
                partial = partial[k]
        return ret

    @staticmethod
    def _update_defaults(to_add: dict, _partial: dict):
        """
        This tries to update the _defaults dictionary with the nested
            partial dict generated by _get_defaults_dict. This WILL
            throw an error if you try to have both a value and a group
            registered under the same name.
        :param to_add:
        :param _partial:
        :return:
        """
        for k, v in to_add.items():
            val_is_dict = isinstance(v, dict)
            if k in _partial:
                existing_is_dict = isinstance(_partial[k], dict)
                if val_is_dict != existing_is_dict:
                    # != is XOR
                    raise KeyError("You cannot register a Group and a Value under"
                                   " the same name.")
                if val_is_dict:
                    Config._update_defaults(v, _partial=_partial[k])
                else:
                    _partial[k] = v
            else:
                _partial[k] = v

    def _register_default(self, key: str, **kwargs):
        if key not in self._defaults:
            self._defaults[key] = {}

        data = deepcopy(kwargs)

        for k, v in data.items():
            to_add = self._get_defaults_dict(k, v)
            self._update_defaults(to_add, self._defaults[key])

    def register_global(self, **kwargs):
        """
        Registers default values for attributes you wish to store in :py:class:`.Config` at a global level.

        You can register a single value or multiple values::

            conf.register_global(
                foo=True
            )

            conf.register_global(
                bar=False,
                baz=None
            )

        You can also now register nested values::

            _defaults = {
                "foo": {
                    "bar": True,
                    "baz": False
                }
            }

            # Will register `foo.bar` == True and `foo.baz` == False
            conf.register_global(
                **_defaults
            )

        You can do the same thing without a :python:`_defaults` dict by using double underscore as a variable
        name separator::

            # This is equivalent to the previous example
            conf.register_global(
                foo__bar=True,
                foo__baz=False
            )
        """
        self._register_default(self.GLOBAL, **kwargs)

    def register_guild(self, **kwargs):
        """
        Registers default values on a per-guild level. See :py:meth:`register_global` for more details.
        """
        self._register_default(self.GUILD, **kwargs)

    def register_channel(self, **kwargs):
        """
        Registers default values on a per-channel level. See :py:meth:`register_global` for more details.
        """
        # We may need to add a voice channel category later
        self._register_default(self.CHANNEL, **kwargs)

    def register_role(self, **kwargs):
        """
        Registers default values on a per-role level. See :py:meth:`register_global` for more details.
        """
        self._register_default(self.ROLE, **kwargs)

    def register_user(self, **kwargs):
        """
        Registers default values on a per-user level (i.e. server-independent). See :py:meth:`register_global` for more details.
        """
        self._register_default(self.USER, **kwargs)

    def register_member(self, **kwargs):
        """
        Registers default values on a per-member level (i.e. server-dependent). See :py:meth:`register_global` for more details.
        """
        self._register_default(self.MEMBER, **kwargs)

    def _get_base_group(self, key: str, *identifiers: str,
                        group_class=Group) -> Group:
        # noinspection PyTypeChecker
        return group_class(
            identifiers=(self.unique_identifier, key) + identifiers,
            defaults=self._defaults.get(key, {}),
            spawner=self.spawner,
            force_registration=self.force_registration
        )

    def guild(self, guild: discord.Guild) -> Group:
        """
        Returns a :py:class:`.Group` for the given guild.

        :param discord.Guild guild: A discord.py guild object.
        """
        return self._get_base_group(self.GUILD, guild.id)

    def channel(self, channel: discord.TextChannel) -> Group:
        """
        Returns a :py:class:`.Group` for the given channel. This does not currently support differences between
        text and voice channels.

        :param discord.TextChannel channel: A discord.py text channel object.
        """
        return self._get_base_group(self.CHANNEL, channel.id)

    def role(self, role: discord.Role) -> Group:
        """
        Returns a :py:class:`.Group` for the given role.

        :param discord.Role role: A discord.py role object.
        """
        return self._get_base_group(self.ROLE, role.id)

    def user(self, user: discord.User) -> Group:
        """
        Returns a :py:class:`.Group` for the given user.

        :param discord.User user: A discord.py user object.
        """
        return self._get_base_group(self.USER, user.id)

    def member(self, member: discord.Member) -> MemberGroup:
        """
        Returns a :py:class:`.MemberGroup` for the given member.

        :param discord.Member member: A discord.py member object.
        """
        return self._get_base_group(self.MEMBER, member.guild.id, member.id,
                                    group_class=MemberGroup)

    async def _all_from_scope(self, scope: str):
        """Get a dict of all values from a particular scope of data.

        :code:`scope` must be one of the constants attributed to
        this class, i.e. :code:`GUILD`, :code:`MEMBER` et cetera.

        IDs as keys in the returned dict are casted to `int` for convenience.

        Default values are also mixed into the data if they have not yet been
        overwritten.
        """
        group = self._get_base_group(scope)
        dict_ = await group()
        ret = {}
        for k, v in dict_.items():
            data = group.defaults
            data.update(v)
            ret[int(k)] = data
        return ret

    def all_guilds(self):
        """Get all guild data as a dict.

        Note
        ----
        The return value of this method will include registered defaults for
        values which have not yet been set.

        Returns
        -------
        types.coroutine
            A coroutine object which must be awaited to yield a `dict` mapping
            :code:`GUILD_ID -> data`.

        """
        return self._all_from_scope(self.GUILD)

    def all_channels(self):
        """Get all channel data as a dict.

        Note
        ----
        The return value of this method will include registered defaults for
        values which have not yet been set.

        Returns
        -------
        types.coroutine
            A coroutine object which must be awaited to yield a `dict` mapping
            :code:`CHANNEL_ID -> data`.

        """
        return self._all_from_scope(self.CHANNEL)

    def all_roles(self):
        """Get all role data as a dict.

        Note
        ----
        The return value of this method will include registered defaults for
        values which have not yet been set.

        Returns
        -------
        types.coroutine
            A coroutine object which must be awaited to yield a `dict` mapping
            :code:`ROLE_ID -> data`.

        """
        return self._all_from_scope(self.ROLE)

    def all_users(self):
        """Get all user data as a dict.

        Note
        ----
        The return value of this method will include registered defaults for
        values which have not yet been set.

        Returns
        -------
        types.coroutine
            A coroutine object which must be awaited to yield a `dict` mapping
            :code:`USER_ID -> data`.

        """
        return self._all_from_scope(self.USER)

    def _all_members_from_guild(self, group: Group, guild_data: dict) -> dict:
        ret = {}
        for member_id, member_data in guild_data.items():
            new_member_data = group.defaults
            new_member_data.update(member_data)
            ret[int(member_id)] = new_member_data
        return ret

    async def all_members(self, guild: discord.Guild=None) -> dict:
        """Get data for all members.

        If :code:`guild` is specified, only the data for the members of that
        guild will be returned. As such, the dict will map
        :code:`MEMBER_ID -> data`. Otherwise, the dict maps
        :code:`GUILD_ID -> MEMBER_ID -> data`.

        Note
        ----
        The return value of this method will include registered defaults for
        values which have not yet been set.

        Parameters
        ----------
        guild : `discord.Guild`, optional
            The guild to get the member data from. Can be omitted if data
            from every member of all guilds is desired.

        Returns
        -------
        dict
            A dictionary of all member data from the given scope.

        """
        ret = {}
        if guild is None:
            group = self._get_base_group(self.MEMBER)
            dict_ = await group()
            for guild_id, guild_data in dict_.items():
                ret[int(guild_id)] = self._all_members_from_guild(
                    group, guild_data)
        else:
            group = self._get_base_group(self.MEMBER, guild.id)
            guild_data = await group()
            ret = self._all_members_from_guild(group, guild_data)
        return ret

    async def _clear_scope(self, *scopes: str):
        """Clear all data in a particular scope.
        
        The only situation where a second scope should be passed in is if
        member data from a specific guild is being cleared.

        If no scopes are passed, then all data is cleared from every scope.

        Parameters
        ----------
        *scopes : str, optional
            The scope of the data. Generally only one scope needs to be
            provided, a second only necessary for clearing member data
            of a specific guild.

            **Leaving blank removes all data from this Config instance.**

        """
        if not scopes:
            group = Group(identifiers=(self.unique_identifier),
                          defaults={},
                          spawner=self.spawner)
        else:
            group = self._get_base_group(*scopes)
        await group.set({})

    def clear_all(self):
        """Clear all data from this Config instance.

        This resets all data to its registered defaults.

        .. important::

            This cannot be undone.

        Returns
        -------
        types.coroutine
            A coroutine which, when awaited, clears all data.

        """
        return self._clear_scope()

    def clear_all_globals(self):
        """Clear all global data.

        This resets all global data to its registered defaults.

        Returns
        -------
        types.coroutine
            A coroutine which, when awaited, clears all global data.

        """
        return self._clear_scope(self.GLOBAL)

    def clear_all_guilds(self):
        """Clear all guild data.

        This resets all guild data to its registered defaults.

        Returns
        -------
        types.coroutine
            A coroutine which, when awaited, clears all guild data.

        """
        return self._clear_scope(self.GUILD)

    def clear_all_channels(self):
        """Clear all channel data.

        This resets all channel data to its registered defaults.

        Returns
        -------
        types.coroutine
            A coroutine which, when awaited, clears all channel data.

        """
        return self._clear_scope(self.CHANNEL)

    def clear_all_roles(self):
        """Clear all role data.

        This resets all role data to its registered defaults.

        Returns
        -------
        types.coroutine
            A coroutine which, when awaited, clears all role data.

        """
        return self._clear_scope(self.ROLE)

    def clear_all_users(self):
        """Clear all user data.

        This resets all user data to its registered defaults.

        Returns
        -------
        types.coroutine
            A coroutine which, when awaited, clears all user data.

        """
        return self._clear_scope(self.USER)

    def clear_all_members(self, guild: discord.Guild=None):
        """Clear all member data.

        This resets all specified member data to its registered defaults.

        Parameters
        ----------
        guild : `discord.Guild`, optional
            The guild to clear member data from. Omit to clear member data from
            all guilds.

        Returns
        -------
        types.coroutine
            A coroutine which, when awaited, clears all specified member data.

        """
        scopes = [self.MEMBER]
        if guild is not None:
            scopes.append(guild.id)
        return self._clear_scope(*scopes)
