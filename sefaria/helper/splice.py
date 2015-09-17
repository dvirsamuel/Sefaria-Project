from sefaria.model import *
from sefaria.system.exceptions import InputError
from sefaria.search import delete_text, index_text
from sefaria.sheets import get_sheets_for_ref, get_sheet, save_sheet
from sefaria.system.database import db

class Splicer(object):
    """
    Simple usage:
    splicer = Splicer()
    splicer.spliceThisIntoNext("Shabbat 7b:11")
    splicer.report()  # optional, to check what it will do
    splicer.execute()

    Code wise, this is built from the perspective of merging the second ref into the first, but after numbers get rewritten, it's all equivalent.
    """
    def __init__(self):
        self.joiner = u" "
        self.first_ref = None # In insert mode, this is the ref to insert after
        self.second_ref = None
        self.section_ref = None
        self.book_ref = None
        self.index = None
        self.first_segment_number = None   # In insert mode, this is the segment to insert after
        self.second_segment_number = None  # In insert mode, this is the segment inserted.
        self.comment_section_lengths = None
        self.commentary_titles = None
        self.commentary_versions = None
        self.versionSet = None
        self.last_segment_number = None
        self.last_segment_ref = None
        self._base_links_to_rewrite = []
        self._commentary_links_to_rewrite = []
        self._report = False
        self._report_error = False
        self._save = False
        self._executed = False
        self._ready = False
        self._mode = None   # "join" or "insert"
        self._sheets_to_update = []

    ####  Setup methods ####

    def spliceThisIntoNext(self, ref):
        assert ref.is_segment_level()
        assert not ref.is_range()
        self._mode = "join"
        self.first_ref = ref
        self.second_ref = ref.next_segment_ref()
        assert self.second_ref
        self._setup_refs()
        self._setup_refs_for_join()
        self._ready = True
        return self

    def splicePrevIntoThis(self, ref):
        assert ref.is_segment_level()
        assert not ref.is_range()
        self._mode = "join"
        self.second_ref = ref
        self.first_ref = ref.prev_segment_ref()
        assert self.first_ref
        self._setup_refs()
        self._setup_refs_for_join()
        self._ready = True
        return self

    # It's a little counter-intuitive, but these are equivalent to their liguistic converse.
    def spliceNextIntoThis(self, ref):
        return self.spliceThisIntoNext(ref)

    def spliceThisIntoPrev(self, ref):
        return self.splicePrevIntoThis(ref)

    def insert_blank_segment_after(self, ref):
        assert ref.is_segment_level()
        assert not ref.is_range()
        self._mode = "insert"
        self.first_ref = ref
        self._setup_refs()
        self.second_segment_number = self.first_segment_number + 1
        self._ready = True
        return self

    def _setup_refs(self):
        self.first_segment_number = self.first_ref.sections[-1]
        self.section_ref = self.first_ref.section_ref()
        self.book_ref = self.first_ref.context_ref(self.first_ref.index_node.depth)
        self.index = self.book_ref.index
        self.commentary_titles = library.get_commentary_version_titles_on_book(self.first_ref.index.title)
        self.commentary_versions = library.get_commentary_versions_on_book(self.first_ref.index.title)
        self.versionSet = VersionSet({"title": self.first_ref.index.title})
        self.last_segment_number = len(self.section_ref.get_state_ja().subarray_with_ref(self.section_ref))
        self.last_segment_ref = self.section_ref.subref(self.last_segment_number)

    def _setup_refs_for_join(self):
        # Derive other refs and variables from from self.first_ref and self.second_ref
        assert self.section_ref == self.second_ref.section_ref(), "Doesn't work across sections"
        self.second_segment_number = self.second_ref.sections[-1]
        self.comment_section_lengths = self._get_comment_section_lengths(self.first_ref)

    @staticmethod
    def _get_comment_section_lengths(ref):
        # todo: merge into _setup_refs_for_join?
        # How many comments are there for each commenter on the base text?
        ret = {}
        for vtitle in library.get_commentary_version_titles_on_book(ref.index.title):
            commentator_book_ref = Ref(vtitle)
            commentator_segment_ref = commentator_book_ref.subref(ref.sections)
            ret[vtitle] = len(commentator_segment_ref.get_state_ja().subarray_with_ref(commentator_segment_ref))
        return ret

    ### Execution Methods ####

    def report(self):
        """
        Report what the splicer will do, but don't make any changes.
        :return:
        """
        if self._executed:
            print "Already executed"
            return
        if not self._ready:
            print "No job given to Splicer"
            return
        self._report = True
        self._save = False
        self._run()
        self._report = False

    def execute(self):
        """
        Execute the splice.
        :return:
        """
        if self._executed:
            print "Already executed"
            return
        if not self._ready:
            print "No job given to Splicer"
            return
        self._save = True
        self._run()
        self._rebuildVersionStates()
        self._executed = True

    ### Internal Methods ###
    def _run(self):
        if self._mode == "join":
            print u"\n---\nMerging Base Text\n---\n"
            self._mergeBaseTextVersionSegments()

            print u"\n---\nMerging Commentary Text\n---\n"
            self._mergeCommentaryVersionSections()

            print u"\n---\nRemoving Segment from Base Texts\n---\n"
            self._removeBaseTextVersionSegments(self.second_ref)

            print u"\n---\nRemoving Section from Commentaries\n---\n"
            self._removeCommentaryVersionsSections(self.second_ref)
        elif self._mode == "insert":
            print u"\n---\nInserting segment Base Text\n---\n"
            self._insertBaseTextVersionSegments()
            print u"\n---\nInserting Section Commentary Texts\n---\n"
            self._insertCommentaryVersionSections()

        else:
            print u"Error: unknown mode - {}".format(self._mode)
            return
        # For all of the below -
        # It takes longer, but we start at the base text, so as not to miss any ranged refs

        # Rewrite links to base text (including links from own commentary)
        print u"\n---\nRewriting Refs to Base Text\n---\n"
        print u"\n---\nRewriting Links\n---\n"
        self._generic_set_rewrite(LinkSet(self.book_ref), ref_attr_name="refs", is_set=True)

        # Note refs
        print u"\n---\nRewriting Note Refs\n---\n"
        self._generic_set_rewrite(NoteSet({"ref": {"$regex": self.book_ref.regex()}}))

        # Translation requests
        print u"\n---\nRewriting Translation Request Refs\n---\n"
        self._generic_set_rewrite(TranslationRequestSet({"ref": {"$regex": self.book_ref.regex()}}))

        # History
        print u"\n---\nRewriting History Refs\n---\n"
        self._generic_set_rewrite(HistorySet({"ref": {"$regex": self.book_ref.regex()}}))
        self._generic_set_rewrite(HistorySet({"new.ref": {"$regex": self.book_ref.regex()}}), ref_attr_name="new", sub_ref_attr_name="ref")
        self._generic_set_rewrite(HistorySet({"new.refs": {"$regex": self.book_ref.regex()}}), ref_attr_name="new", sub_ref_attr_name="refs", is_set=True)
        self._generic_set_rewrite(HistorySet({"old.ref": {"$regex": self.book_ref.regex()}}), ref_attr_name="old", sub_ref_attr_name="ref")
        self._generic_set_rewrite(HistorySet({"old.refs": {"$regex": self.book_ref.regex()}}), ref_attr_name="old", sub_ref_attr_name="refs", is_set=True)

        print u"\n---\nRewriting Refs to Commentary\n---\n"
        for commentary_title in self.commentary_titles:
            # Rewrite links to commentary (including to base text)
            print u"\n---\n{}\n---\n".format(commentary_title)
            print u"\n---\nRewriting Links\n---\n"
            self._generic_set_rewrite(LinkSet(Ref(commentary_title)), ref_attr_name="refs", is_set=True, commentary=True)
            print u"\n---\nRewriting Note Refs\n---\n"
            self._generic_set_rewrite(NoteSet({"ref": {"$regex": Ref(commentary_title).regex()}}), commentary=True)
            print u"\n---\nRewriting Translation Request Refs\n---\n"
            self._generic_set_rewrite(TranslationRequestSet({"ref": {"$regex": Ref(commentary_title).regex()}}), commentary=True)

            # History?
            print u"\n---\nRewriting History Refs\n---\n"
            self._generic_set_rewrite(HistorySet({"ref": {"$regex": Ref(commentary_title).regex()}}), commentary=True)
            self._generic_set_rewrite(HistorySet({"new.ref": {"$regex": Ref(commentary_title).regex()}}), ref_attr_name="new", sub_ref_attr_name="ref", commentary=True)
            self._generic_set_rewrite(HistorySet({"new.refs": {"$regex": Ref(commentary_title).regex()}}), ref_attr_name="new", sub_ref_attr_name="refs", is_set=True, commentary=True)
            self._generic_set_rewrite(HistorySet({"old.ref": {"$regex": Ref(commentary_title).regex()}}), ref_attr_name="old", sub_ref_attr_name="ref", commentary=True)
            self._generic_set_rewrite(HistorySet({"old.refs": {"$regex": Ref(commentary_title).regex()}}), ref_attr_name="old", sub_ref_attr_name="refs", is_set=True, commentary=True)

        # Source sheet refs
        print u"\n---\nRewriting Source Sheet Refs\n---\n"
        self._find_sheets()
        self._clean_sheets()

        # alt structs?
        print u"\n---\nRewriting Alt Struct Refs\n---\n"
        self._rewrite_alt_structs()

        print u"\n---\nPushing changes to Elastic Search\n---\n"
        self._clean_elastisearch()

        #summaries.update_summaries_on_change(c_oref.book)

    def _insertBaseTextVersionSegments(self):
        # Inserts are self.first_ref
        for v in self.versionSet:
            assert isinstance(v, Version)
            tc = TextChunk(self.section_ref, lang=v.language, vtitle=v.versionTitle)
            if len(tc.text) <= self.first_segment_number:
                continue
            tc.text.insert(self.first_segment_number, "")
            if self._report:
                print u"Inserting segment after {} ({})".format(self.first_ref.normal(), v.versionTitle)
            if self._save:
                tc.save()

    def _insertCommentaryVersionSections(self):
        # Inserts are self.first_ref
        if self.first_ref.is_commentary():
            return

        for v in self.commentary_versions:
            assert isinstance(v, Version)
            commentator_chapter_ref = Ref(v.title).subref(self.section_ref.sections)
            commentator_line_ref = Ref(v.title).subref(self.first_ref.sections)
            tc = TextChunk(commentator_chapter_ref, lang=v.language, vtitle=v.versionTitle)
            if len(tc.text) <= self.first_segment_number:
                continue
            tc.text.insert(self.first_segment_number, [])
            if self._report:
                print u"Inserting commentary segment after {} ({})".format(commentator_line_ref.normal(), v.versionTitle)
            if self._save:
                tc.save()

    def _mergeBaseTextVersionSegments(self):
        # for each version, merge the text
        for v in self.versionSet:
            assert isinstance(v, Version)
            first_tc = TextChunk(self.first_ref, lang=v.language, vtitle=v.versionTitle)
            second_tc = TextChunk(self.second_ref, lang=v.language, vtitle=v.versionTitle)
            if not (first_tc.is_empty() and second_tc.is_empty()):
                first_tc.text = first_tc.text + self.joiner + second_tc.text
                if self._report:
                    print u"{}: {} and {} merging to become {}".format(v.versionTitle, self.first_ref.normal(), self.second_ref.normal(), first_tc.text)
                if self._save:
                    first_tc.save()

    def _mergeCommentaryVersionSections(self):
        # Merge comments for all commentary on this text
        if not self.first_ref.is_commentary():
            for v in self.commentary_versions:
                assert isinstance(v, Version)
                commentator_book_ref = Ref(v.title)
                commentator_section_ref = commentator_book_ref.subref(self.section_ref.sections)
                commentator_segment_ref = commentator_book_ref.subref(self.first_ref.sections)
                tc = TextChunk(commentator_section_ref, lang=v.language, vtitle=v.versionTitle)
                if len(tc.text) < self.second_segment_number:
                    continue

                # Pad first section to uniform length, as derived from state, then add the next section on to the end
                comment_section_length = self.comment_section_lengths.get(v.title)
                assert len(tc.text[self.first_segment_number - 1]) <= comment_section_length
                tc.text[self.first_segment_number - 1] = tc.text[self.first_segment_number - 1] + [list() for _ in range(len(tc.text[self.first_segment_number - 1]), comment_section_length)] + tc.text[self.second_segment_number - 1]
                if self._report:
                    print u"{} ({}) becoming\n{}".format(commentator_segment_ref.normal(), v.versionTitle, tc.text[self.first_segment_number - 1])
                if self._save:
                    tc.save()

    def _removeBaseTextVersionSegments(self, local_ref):
        assert local_ref.is_segment_level()
        local_section_ref = local_ref.section_ref()
        local_segment_number = local_ref.sections[-1]

        # Remove segment from all versions that have it
        for v in local_section_ref.versionset():
            tc = TextChunk(local_section_ref, lang=v.language, vtitle=v.versionTitle)
            if len(tc.text) < local_segment_number:
                continue
            tc.text = tc.text[:local_segment_number - 1] + tc.text[local_segment_number:]
            if self._report:
                print u"Removing {} ({})".format(local_ref.normal(), v.versionTitle)
            if self._save:
                tc.save()

    def _removeCommentaryVersionsSections(self, local_ref):
        assert local_ref.is_segment_level()
        local_section_ref = local_ref.section_ref()
        local_segment_number = local_ref.sections[-1]

        # Remove segment from all commentary on this text
        if local_ref.is_commentary():
            return

        for v in self.commentary_versions:
            assert isinstance(v, Version)
            commentator_chapter_ref = Ref(v.title).subref(local_section_ref.sections)
            commentator_line_ref = Ref(v.title).subref(local_ref.sections)
            tc = TextChunk(commentator_chapter_ref, lang=v.language, vtitle=v.versionTitle)
            if len(tc.text) < local_segment_number:
                continue
            tc.text = tc.text[:local_segment_number - 1] + tc.text[local_segment_number:]
            if self._report:
                print u"Removing {} ({})".format(commentator_line_ref.normal(), v.versionTitle)
            if self._save:
                tc.save()

    def _needs_rewrite(self, old_ref, commentary=False):
        # There is no difference here between join and insert - anything after first_ref needs to be rewritten
        assert isinstance(old_ref, Ref)

        def simple_needs_rewrite(old_simple_ref):
            assert isinstance(old_simple_ref, Ref)

            if (len(old_simple_ref.sections) >= self.first_ref.index_node.depth
                and old_simple_ref.sections[self.first_ref.index_node.depth - 2] == self.section_ref.sections[-1]
                and old_simple_ref.sections[self.first_ref.index_node.depth - 1] > self.first_segment_number
               ):
                return True
            return False

        if old_ref.is_commentary() != commentary:
            return False
        if (not commentary) and (old_ref.index != self.first_ref.index):
            return False
        if commentary and old_ref.index.b_index != self.first_ref.index:
            return False

        if old_ref.is_range():
            return simple_needs_rewrite(old_ref.starting_ref()) or simple_needs_rewrite(old_ref.ending_ref())
        return simple_needs_rewrite(old_ref)

    def _rewrite(self, old_ref, commentary=False):
        assert isinstance(old_ref, Ref)

        def insert_rewrite(old_simple_ref):
            segment_depth = self.first_ref.index_node.depth - 1
            if old_simple_ref.sections[segment_depth] > self.first_segment_number:
                d = old_simple_ref._core_dict()
                d["sections"][segment_depth] += 1
                d["toSections"] = d["sections"]
                return Ref(_obj=d)

        def join_rewrite(old_simple_ref):
            segment_depth = self.first_ref.index_node.depth - 1
            if commentary and old_simple_ref.is_segment_level() and old_simple_ref.sections[segment_depth] == self.second_segment_number:
                # Position of comment has changed
                d = old_simple_ref._core_dict()
                d["sections"][-2] -= 1
                d["sections"][-1] += self.comment_section_lengths.get(old_simple_ref.index.title)
                d["toSections"] = d["sections"]
                return Ref(_obj=d)
            elif old_simple_ref.sections[segment_depth] > self.first_segment_number:
                if not commentary:
                    return old_simple_ref.prev_segment_ref()
                else:
                    d = old_simple_ref._core_dict()
                    d["sections"][segment_depth] -= 1
                    d["toSections"] = d["sections"]
                    return Ref(_obj=d)
            return old_simple_ref

        _rewrite_method = insert_rewrite if self._mode == "insert" else join_rewrite
        if old_ref.is_range():
            return _rewrite_method(old_ref.starting_ref()).to(_rewrite_method(old_ref.ending_ref()))
        return _rewrite_method(old_ref)

    def _generic_set_rewrite(self, model_set, commentary=False, ref_attr_name="ref", sub_ref_attr_name=None, is_set=False):
        for n in model_set:
            needs_save = False

            try:
                if sub_ref_attr_name:
                    intermediate_obj = getattr(n, ref_attr_name)
                    rawref = intermediate_obj[sub_ref_attr_name]
                else:
                    rawref = getattr(n, ref_attr_name)

                if is_set:
                    refs = [Ref(r) for r in rawref]
                else:
                    refs = [Ref(rawref)]

            except InputError as e:
                if self._report_error:
                    print e
                continue

            for i, ref in enumerate(refs):
                if self._needs_rewrite(ref, commentary=commentary):
                    needs_save = True
                    refs[i] = self._rewrite(ref, commentary=commentary)

            if needs_save:
                if is_set:
                    refs = [r.normal() for r in refs]
                else:
                    refs = refs[0].normal()

                if sub_ref_attr_name:
                    intermediate_obj[sub_ref_attr_name] = refs
                    setattr(n, ref_attr_name, intermediate_obj)
                else:
                    setattr(n, ref_attr_name, refs)

                if self._report:
                    print u"{}.{}{} - converting {} to {}".format(
                        n.__class__.__name__,
                        ref_attr_name,
                        (u"." + sub_ref_attr_name) if sub_ref_attr_name else "",
                        rawref,
                        refs)
                if self._save:
                    n.save()

    def _rewrite_alt_structs(self):
        if not self.index.has_alt_structures():
            return
        needs_save = False
        for name, struct in self.index.get_alt_structures().iteritems():
            for map_node in struct.get_leaf_nodes():
                assert map_node.depth <= 1, "Need to write some code to handle alt structs with depth > 1!"
                wr = Ref(map_node.wholeRef)
                if self._needs_rewrite(wr, wr.is_commentary()):
                    needs_save = True
                    map_node.wholeRef = self._rewrite(wr, wr.is_commentary()).normal()
                for i, r in enumerate(map_node.refs):
                    ref = Ref(r)
                    if self._needs_rewrite(ref, ref.is_commentary()):
                        needs_save = True
                        map_node.refs[i] = self._rewrite(ref, ref.is_commentary()).normal()
        if needs_save:
            if self._report:
                print "Saving {} alt structs".format(self.index.title)
            if self._save:
                self.index.save()

    def _find_sheets(self):
        def _get_sheets_with_ref(oref):
            ref_re = oref.regex()
            sheets = db.sheets.find({"included_refs": {"$regex": ref_re}}, {"id": 1})
            return [s["id"] for s in sheets]

        self._sheets_to_update += _get_sheets_with_ref(self.section_ref)
        for commentary_title in self.commentary_titles:
            commentator_book_ref = Ref(commentary_title)
            commentator_chapter_ref = commentator_book_ref.subref(self.section_ref.sections)
            self._sheets_to_update += _get_sheets_with_ref(commentator_chapter_ref)

    def _clean_sheets(self):

        def rewrite_source(source):
            needs_save = False
            if "ref" in source:
                ref = Ref(source["ref"])
                if self._needs_rewrite(ref, ref.is_commentary()):
                    if self._report:
                        print "Sheet refs - rewriting {} to {}".format(ref.normal(), self._rewrite(ref, ref.is_commentary()).normal())
                    needs_save = True
                    source["ref"] = self._rewrite(ref, ref.is_commentary()).normal()
            if "subsources" in source:
                for subsource in source["subsources"]:
                    needs_save = rewrite_source(subsource) or needs_save
            return needs_save

        for sid in self._sheets_to_update:
            needs_save = False
            sheet = db.sheets.find_one({"id": sid})
            if not sheet:
                print "Likely error - can't load sheet {}".format(sid)
            for source in sheet["sources"]:
                if rewrite_source(source):
                    needs_save = True
            if needs_save:
                if self._report:
                    print "Saving modified sheet #{}".format(sheet["id"])
                if self._save:
                    save_sheet(sheet, sheet["owner"])

    def _clean_elastisearch(self):
        """
        Re-index modified chapters in ES
        Delete last segment that hangs off the edge of base text and commentaries after a merge
        """

        from sefaria.settings import SEARCH_INDEX_ON_SAVE
        if not SEARCH_INDEX_ON_SAVE:
            return

        for v in self.versionSet:
            if self._report:
                print "ElasticSearch: Reindexing {} / {} / {}".format(self.section_ref.normal(), v.versionTitle, v.language)
            if self._save:
                index_text(self.section_ref, v.versionTitle, v.language)

            # If this is not a Bavli ref, it's been indexed by segment.  Delete the last dangling segment
            if not self.section_ref.is_bavli():
                if self._report:
                    print "ElasticSearch: Deleting {} / {} / {}".format(self.last_segment_ref.normal(), v.versionTitle, v.language)
                if self._save:
                    delete_text(self.last_segment_ref, v.versionTitle, v.language)

        for commentary_title in self.commentary_titles:
            commentator_book_ref = Ref(commentary_title)
            commentator_chapter_ref = commentator_book_ref.subref(self.section_ref.sections)
            last_commentator_section_ref = commentator_book_ref.subref(self.last_segment_ref.sections)

            for v in VersionSet({"title": commentary_title}):
                for i in range(1, self.last_segment_number):  # no need to do the last one; it's deleted below
                    commentor_section_ref = commentator_chapter_ref.subref(i)
                    if self._report:
                        print "ElasticSearch: Reindexing {} / {} / {}".format(commentor_section_ref.normal(), v.versionTitle, v.language)
                    if self._save:
                        index_text(commentor_section_ref, v.versionTitle, v.language)

                last_segment = len(last_commentator_section_ref.get_state_ja().subarray_with_ref(last_commentator_section_ref))

                if commentator_book_ref.is_bavli() and last_segment > 0:
                    if self._report:
                        print "ElasticSearch: Deleting {} / {} / {}".format(last_commentator_section_ref.normal(), v.versionTitle, v.language)
                    if self._save:
                        delete_text(last_commentator_section_ref, v.versionTitle, v.language)
                else:
                    for i in range(last_segment):
                        comment_ref = last_commentator_section_ref.subref(i+1)
                        if self._report:
                            print "ElasticSearch: Deleting {} / {} / {}".format(comment_ref.normal(), v.versionTitle, v.language)
                        if self._save:
                            delete_text(comment_ref, v.versionTitle, v.language)

    def _rebuildVersionStates(self):
        # Refresh the version state of main text and commentary
        VersionState(self.first_ref.index).refresh()
        if not self.first_ref.is_commentary():
            for vt in  self.commentary_titles:
                VersionState(vt).refresh()

    def __eq__(self, other):
        return self._mode == other._mode and self.first_ref == other.first_ref and self.second_ref == other.second_ref

    def __ne__(self, other):
        return not self.__eq__(other)
